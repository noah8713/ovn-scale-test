"""
Usage python compare_oflow_count.py task1_oflow.txt task2_oflow.txt

generate task1_oflow.txt and  task2_oflow.txt using each task:
rally task results 50735c0d-be3f-4bf4-bace-a91601116312 >> task1_oflow.txt
rally task results 50735c0d-be3f-4bf4-bace-a91601226312 >> task2_oflow.txt

"""
import json
import re
import sys

oflow_task_res1 = sys.argv[1]
oflow_task_res2 = sys.argv[2]


class oflow_check():

	def compare_oflow_data(self):

	    oflow_dict_list_1 = self.get_oflow_dict(oflow_task_res1)
	    oflow_dict_list_2 = self.get_oflow_dict(oflow_task_res2)
            print oflow_dict_list_1
	    print oflow_dict_list_2
            shared_items = set(oflow_dict_list_1.items()) - set(oflow_dict_list_2.items())
            if not shared_items:
    	        print "Yay! Openflow count with both the runs is same"
    	    else:
    		print "Warning! Openflow count is not same on both runs."
                print "mismatch data is %s" %list(shared_items)

	def parse_file_to_json(self, fname):
	    oflow_task_data = ''
	    with open(fname) as f:
	        oflow_task_data += f.read()
	    oflow_task_data = json.loads(oflow_task_data.rstrip()[1:-1])
	    return oflow_task_data

	def get_oflow_dict(self, fname):
	    data = self.parse_file_to_json(fname)
	    oflow_data = data.get('result', None)
	    if oflow_data:
		oflow_data_output = oflow_data[0].get('output', None)
	    chart_data = oflow_data_output.get('additive', None)
	    if chart_data:
		oflow_data = chart_data[0]['data']
	    oflow_data = tuple(oflow_data)
	    oflow_dict_list = dict((i,j) for i,j in oflow_data)
	    return oflow_dict_list


if __name__ == "__main__":
     oflow_check().compare_oflow_data()
