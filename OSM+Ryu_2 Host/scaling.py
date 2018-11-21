import requests
from scapy.all import *

os.environ["OSM_HOSTNAME"]="127.0.0.1"
os.environ["OSM_SOL005"]="True"

CPU_MIN_THRESHOLD = 20
CPU_MAX_THRESHOLD = 70

# Check cpu_utilization metric every minute
QUERYING_INTERVAL = 60 
# Scaling action will only proceed if a vdu was found to violate the threshold for x periods.
X_PERIOD = 3 

scaling_MAC = '02:0a:12:14:0c:05'


instances = ['P1']

scale_up_count = 0
piid_pending_deletion = {}

scaling_socket = conf.L2socket(iface='enp3s0')

# 'http://localhost:9091/api/v1/query?query=cpu_utilization'
def collect_metrics():
	reply = requests.get('http://localhost:9091/api/v1/query?query=cpu_utilization')
	metric_list = eval(reply.text)["data"]["result"]
	report = {}
	for elem in metric_list:
		report[elem["metric"]["vdu_name"].replace("-1-piid-VM-1","")] = float(elem["value"][1])
	# Return a list of piid cpu utilization in ascending order
	return report

def create_new_piid():
	global instances
	# Instantiate a new piid vnf
	ns_name = 'P'+str(len(instances)+1)
	os.system("osm ns-create --ns_name "+ns_name+" --nsd_name piid-ns --vim_account LOCAL_openstack --config \'{ vld : [ { name: mgmt-vl, vim-network-name: private} ] }\' ")
	instances.append(ns_name)

def delete_piid(ns_name):
	os.system("osm ns-delete "+ns_name)
	instances.remove(ns_name)

def send_to_load_balancer(req_str):
	global scaling_socket
	global scaling_MAC
	pkt=Ether(dst=scaling_MAC)/IP(src='192.168.100.78',dst='192.168.100.79')/UDP(sport=1234,dport=1234)/req_str
	scaling_socket.send(pkt)


while True:
	# collect metrics
	metrics = collect_metrics()
	print "Collected Metrics:",metrics,"\n"

	if len(metrics)==0:
		time.sleep(30)
		continue

	for ns_name in piid_pending_deletion.keys():
		if metrics[ns_name]<1:
			piid_pending_deletion[ns_name]+=1
			if piid_pending_deletion[ns_name]==3:
				delete_piid(ns_name)
				metrics.pop(ns_name)
				piid_pending_deletion.pop(ns_name)
			else:
				send_to_load_balancer("underload:"+ns_name[1:])
		else:
			piid_pending_deletion.pop(ns_name)

	metrics = sorted(metrics.items(),key=lambda kv: kv[1])
	most_loaded_piid = metrics[-1][0]
	most_loaded_cpu_util = metrics[-1][1]
	least_loaded_piid = metrics[0][0]
	least_loaded_cpu_util = metrics[0][1]

	# scale up ?
	if most_loaded_cpu_util >= CPU_MAX_THRESHOLD:
		print "Overloaded piid: ",most_loaded_piid," --- ",most_loaded_cpu_util,"\n"
		if least_loaded_cpu_util >= CPU_MAX_THRESHOLD:
			print "Case 1: scale up\n"
			create_new_piid()
			scale_up_count = 0
			time.sleep(2*QUERYING_INTERVAL)
		else:
			scale_up_count+=1
			print "Case 2 and 3: scale_up_count=",scale_up_count,
			if scale_up_count == 3:
				print " action=scale up\n"
				create_new_piid()
				scale_up_count = 0
				time.sleep(2*QUERYING_INTERVAL)
			else:
				print " action=send overload signal\n"
				send_to_load_balancer("overload")
	else:
		scale_up_count = 0
		# scale down ? (maintain at least 1 piid instance)
		if len(instances)-len(piid_pending_deletion)>1 and least_loaded_cpu_util <= CPU_MIN_THRESHOLD:
			if least_loaded_piid not in piid_pending_deletion:
				print "Case 5 and 6: send underload signal\n"
				print "Underloaded piid: ",least_loaded_piid," --- ",least_loaded_cpu_util,"\n"
				piid_pending_deletion[least_loaded_piid]=0
				if least_loaded_cpu_util < 1:
					piid_pending_deletion[least_loaded_piid]+=1
				send_to_load_balancer("underload:"+least_loaded_piid[1:])

	time.sleep(QUERYING_INTERVAL)			

