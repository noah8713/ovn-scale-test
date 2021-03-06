# Copyright 2016 Ebay Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from rally_ovs.plugins.ovs import scenario
from rally.task import atomic
from rally.common import logging
from rally import exceptions
from rally_ovs.plugins.ovs import ovnclients
from rally_ovs.plugins.ovs import utils
import random
import netaddr

LOG = logging.getLogger(__name__)


class OvnScenario(ovnclients.OvnClientMixin, scenario.OvsScenario):
    RESOURCE_NAME_FORMAT = "lswitch_XXXXXX_XXXXXX"


    '''
    return: [{"name": "lswitch_xxxx_xxxxx", "cidr": netaddr.IPNetwork}, ...]
    '''
    @atomic.action_timer("ovn.create_lswitch")
    def _create_lswitches(self, lswitch_create_args, num_switches=-1):
        print("create lswitch")
        return super(OvnScenario, self)._create_lswitches(lswitch_create_args, num_switches)

    @atomic.optional_action_timer("ovn.list_lswitch")
    def _list_lswitches(self):
        print("list lswitch")
        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox")
        ovn_nbctl.enable_batch_mode(False)
        return ovn_nbctl.lswitch_list()

    @atomic.action_timer("ovn.delete_lswitch")
    def _delete_lswitch(self, lswitches):
        print("delete lswitch")
        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox")
        ovn_nbctl.enable_batch_mode()
        for lswitch in lswitches:
            ovn_nbctl.lswitch_del(lswitch["name"])

        ovn_nbctl.flush()


    def _get_or_create_lswitch(self, lswitch_create_args=None):
        pass

    @atomic.action_timer("ovn.create_lport")
    def _create_lports(self, lswitch, lport_create_args = [], lport_amount=1,
                       lport_ip_shift = 1):
        LOG.info("create %d lports on lswitch %s" % \
                            (lport_amount, lswitch["name"]))

        self.RESOURCE_NAME_FORMAT = "lport_XXXXXX_XXXXXX"

        batch = lport_create_args.get("batch", lport_amount)
        port_security = lport_create_args.get("port_security", True)

        LOG.info("Create lports method: %s" % self.install_method)
        install_method = self.install_method

        network_cidr = lswitch.get("cidr", None)
        ip_addrs = None
        if network_cidr:
            end_ip = network_cidr.ip + lport_amount + lport_ip_shift
            if not end_ip in network_cidr:
                message = _("Network %s's size is not big enough for %d lports.")
                raise exceptions.InvalidConfigException(
                            message  % (network_cidr, lport_amount))

            ip_addrs = netaddr.iter_iprange(network_cidr.ip + lport_ip_shift,
                                            network_cidr.last)

        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox", install_method)
        ovn_nbctl.enable_batch_mode()

        base_mac = [i[:2] for i in self.task["uuid"].split('-')]
        base_mac[0] = str(hex(int(base_mac[0], 16) & 254))
        base_mac[3:] = ['00']*3

        flush_count = batch
        lports = []
        for i in range(lport_amount):
            name = self.generate_random_name()
            lport = ovn_nbctl.lswitch_port_add(lswitch["name"], name)

            ip = str(ip_addrs.next()) if ip_addrs else ""
            mac = utils.get_random_mac(base_mac)

            ovn_nbctl.lport_set_addresses(name, [mac, ip])
            if port_security:
                ovn_nbctl.lport_set_port_security(name, mac)

            lports.append(lport)

            flush_count -= 1
            if flush_count < 1:
                ovn_nbctl.flush()
                flush_count = batch

        ovn_nbctl.flush()  # ensure all commands be run
        ovn_nbctl.enable_batch_mode(False)
        return lports


    @atomic.action_timer("ovn.delete_lport")
    def _delete_lport(self, lports):
        print("delete lport")
        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox")
        ovn_nbctl.enable_batch_mode()
        for lport in lports:
            ovn_nbctl.lport_del(lport["name"])

        ovn_nbctl.flush()


    @atomic.action_timer("ovn.list_lports")
    def _list_lports(self, lswitches, install_method = "sandbox"):
        print("list lports")
        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox", install_method)
        ovn_nbctl.enable_batch_mode(False)
        for lswitch in lswitches:
            LOG.info("list lports on lswitch %s" % lswitch["name"])
            ovn_nbctl.lport_list(lswitch["name"])



    @atomic.action_timer("ovn.create_acl")
    def _create_acl(self, lswitch, lports, acl_create_args, acls_per_port):
        sw = lswitch["name"]
        LOG.info("create %d ACLs on lswitch %s" % (acls_per_port, sw))

        direction = acl_create_args.get("direction", "to-lport")
        priority = acl_create_args.get("priority", 1000)
        action = acl_create_args.get("action", "allow")
        address_set = acl_create_args.get("address_set", "")

        '''
        match template: {
            "direction" : "<inport/outport>",
            "lport" : "<swicth port>",
            "address_set" : "<address_set id>"
            "l4_port" : "<l4 port number>",
        }
        '''
        match_template = acl_create_args.get("match",
                                             "%(direction)s == %(lport)s && \
                                             ip4 && udp && udp.src == %(l4_port)s")
        if direction == "from-lport":
            p = "inport"
        else:
            p = "outport"

        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox", self.install_method)
        ovn_nbctl.enable_batch_mode()
        for lport in lports:
            for i in range(acls_per_port):
                match = match_template % { 'direction' : p,
                                           'lport' : lport["name"],
                                           'address_set' : address_set,
                                           'l4_port' : 100 + i }
                ovn_nbctl.acl_add(sw, direction, priority, match, action)
            ovn_nbctl.flush()


    @atomic.action_timer("ovn.list_acl")
    def _list_acl(self, lswitches):
        LOG.info("list ACLs")
        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox", self.install_method)
        ovn_nbctl.enable_batch_mode(False)
        for lswitch in lswitches:
            LOG.info("list ACLs on lswitch %s" % lswitch["name"])
            ovn_nbctl.acl_list(lswitch["name"])


    @atomic.action_timer("ovn.delete_all_acls")
    def _delete_all_acls_in_lswitches(self, lswitches):
        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.enable_batch_mode(True)
        for lswitch in lswitches:
            self._delete_acls(lswitch)
        ovn_nbctl.flush()

    def _delete_acls(self, lswitch, direction=None, priority=None,
                     match=None, flush=False):
        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox")
        LOG.info("delete ACLs on lswitch %s" % lswitch["name"])
        ovn_nbctl.acl_del(lswitch["name"], direction, priority, match)
        if flush:
            ovn_nbctl.flush()


    @atomic.action_timer("ovn_network.create_routers")
    def _create_routers(self, router_create_args):
        LOG.info("Create Logical routers")
        return super(OvnScenario, self)._create_routers(router_create_args)

    @atomic.action_timer("ovn_network.connect_network_to_router")
    def _connect_networks_to_routers(self, lnetworks, lrouters, networks_per_router):
        super(OvnScenario, self)._connect_networks_to_routers(lnetworks,
                                                              lrouters,
                                                              networks_per_router)

    @atomic.action_timer("ovn_network.create_phynet")
    def _create_phynet(self, lswitches, physnet, batch):
        LOG.info("Create phynet method: %s" % self.install_method)
        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox", self.install_method)
        ovn_nbctl.enable_batch_mode()

        flush_count = batch
        for lswitch in lswitches:
            network = lswitch["name"]
            port = "provnet-%s" % network
            ovn_nbctl.lswitch_port_add(network, port)
            ovn_nbctl.lport_set_addresses(port, ["unknown"])
            ovn_nbctl.lport_set_type(port, "localnet")
            ovn_nbctl.lport_set_options(port, "network_name=%s" % physnet)

            flush_count -= 1
            if flush_count < 1:
                ovn_nbctl.flush()
                flush_count = batch

        ovn_nbctl.flush()

    # NOTE(huikang): num_networks overides the "amount" in network_create_args
    def _create_networks(self, network_create_args, num_networks=-1):
        physnet = network_create_args.get("physical_network", None)
        lswitches = self._create_lswitches(network_create_args, num_networks)
        batch = network_create_args.get("batch", len(lswitches))

        if physnet != None:
            self._create_phynet(lswitches, physnet, batch)

        return lswitches

    def _bind_ports_and_wait(self, lports, sandboxes, port_bind_args):
        port_bind_args = port_bind_args or {}
        wait_up = port_bind_args.get("wait_up", False)
        # "wait_sync" takes effect only if wait_up is True.
        # By default we wait for all HVs catching up with the change.
        wait_sync = port_bind_args.get("wait_sync", "hv")
        if wait_sync.lower() not in ['hv', 'sb', 'none']:
            raise exceptions.InvalidConfigException(_(
                "Unknown value for wait_sync: %s. "
                "Only 'hv', 'sb' and 'none' are allowed.") % wait_sync)

        LOG.info("Bind lports method: %s" % self.install_method)

        self._bind_ports(lports, sandboxes, port_bind_args)
        if wait_up:
            self._wait_up_port(lports, wait_sync)

    @atomic.action_timer("ovn_network.bind_port")
    def _bind_ports(self, lports, sandboxes, port_bind_args):
        sandbox_num = len(sandboxes)
        lport_num = len(lports)
        lport_per_sandbox = (lport_num + sandbox_num - 1) / sandbox_num

        if (len(lports) < len(sandboxes)):
            for lport in lports:
                sandbox_data = random.choice(sandboxes)
                farm = sandbox_data['farm']
                sandbox = sandbox_data['name']
                ovs_vsctl = self.farm_clients(farm, "ovs-vsctl")

                ovs_vsctl.set_sandbox(sandbox, self.install_method)
                ovs_vsctl.enable_batch_mode()
                port_name = lport["name"]
                LOG.info("bind %s to %s on %s" % (port_name, sandbox, farm))

                ovs_vsctl.add_port('br-int', port_name)
                ovs_vsctl.db_set('Interface', port_name,
                                 ('external_ids', {"iface-id": port_name,
                                                   "iface-status": "active"}),
                                 ('admin_state', 'up'))
                ovs_vsctl.flush()

        else:
            j = 0
            for i in range(0, len(lports), lport_per_sandbox):
                lport_slice = lports[i:i+lport_per_sandbox]

                sandbox = sandboxes[j]["name"]
                farm = sandboxes[j]["farm"]
                ovs_vsctl = self.farm_clients(farm, "ovs-vsctl")
                ovs_vsctl.set_sandbox(sandbox, self.install_method)
                ovs_vsctl.enable_batch_mode()
                for lport in lport_slice:
                    port_name = lport["name"]

                    LOG.info("bind %s to %s on %s" % (port_name, sandbox, farm))

                    ovs_vsctl.add_port('br-int', port_name)
                    ovs_vsctl.db_set('Interface', port_name,
                                     ('external_ids', {"iface-id":port_name,
                                                       "iface-status":"active"}),
                                     ('admin_state', 'up'))
                ovs_vsctl.flush()
                j += 1

    @atomic.action_timer("ovn_network.wait_port_up")
    def _wait_up_port(self, lports, wait_sync):
        LOG.info("wait port up. sync: %s" % wait_sync)
        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox", self.install_method)
        ovn_nbctl.enable_batch_mode(True)

        for lport in lports:
            ovn_nbctl.wait_until('Logical_Switch_Port', lport["name"], ('up', 'true'))

        if wait_sync != "none":
            ovn_nbctl.sync(wait_sync)

    @atomic.action_timer("ovn_network.list_oflow_count_for_sandboxes")
    def _list_oflow_count_for_sandboxes(self, sandboxes,
                                           sandbox_args):
        install_method = self.install_method
        oflow_data = []
        for sandbox in sandboxes:
            sandbox_name = sandbox["name"]
            farm = sandbox["farm"]
            ovs_ofctl = self.farm_clients(farm, "ovs-ofctl")
            ovs_ofctl.set_sandbox(sandbox_name, install_method)
            bridge = sandbox_args.get('bridge', 'br-int')
            lflow_count = ovs_ofctl.dump_flows(bridge)

            LOG.debug('openflow count on %s is %s' % (sandbox_name, lflow_count))
            oflow_data.append([sandbox_name, lflow_count])

        # Leverage additive plot as each sandbox has just one openflow count.
        additive_oflow_data = {
            "title": "Openflow count on each sandbox in StackedArea",
            "description": "Openflow count on each sandbox",
            "chart_plugin": "StackedArea", "data": oflow_data
        }
        self.add_output(additive_oflow_data)

    def _create_address_set(self, set_name, address_list):
        LOG.info("create %s address_set [%s]" % (set_name, address_list))

        name = "name=\"" + set_name + "\""
        addr_list="\"" + address_list + "\""

        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox", self.install_method)
        ovn_nbctl.create("Address_Set", name, ('addresses', addr_list))
        ovn_nbctl.flush()

    def _address_set_add_addrs(self, set_name, address_list):
        LOG.info("add [%s] to address_set %s" % (address_list, set_name))

        name = "\"" + set_name + "\""
        addr_list="\"" + address_list + "\""

        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox", self.install_method)
        ovn_nbctl.add("Address_Set", name, ('addresses', ' ', addr_list))
        ovn_nbctl.flush()

    def _address_set_remove_addrs(self, set_name, address_list):
        LOG.info("remove [%s] from address_set %s" % (address_list, set_name))

        name = "\"" + set_name + "\""
        addr_list="\"" + address_list + "\""

        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox", self.install_method)
        ovn_nbctl.remove("Address_Set", name, ('addresses', ' ', addr_list))
        ovn_nbctl.flush()

    def _remove_address_set(self, set_name):
        LOG.info("remove %s address_set" % set_name)

        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox", self.install_method)
        ovn_nbctl.destroy("Address_Set", set_name)
        ovn_nbctl.flush()

    def _get_address_set(self, set_name):
        LOG.info("get %s address_set" % set_name)

        ovn_nbctl = self.controller_client("ovn-nbctl")
        ovn_nbctl.set_sandbox("controller-sandbox", self.install_method)
        ovn_nbctl.enable_batch_mode(False)
        return ovn_nbctl.get("Address_Set", set_name, 'addresses')
