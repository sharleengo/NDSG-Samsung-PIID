from scapy.all import *
import datetime
import threading


start_time=None

active_interface = [intf for intf in get_if_list() if "e" in intf][0]
load_balancer_MAC = get_if_hwaddr(active_interface)
load_balancer_IP = os.popen('ip addr show '+active_interface).read().split("inet ")[1].split("/")[0]

ryu1_MAC = '03:14:20:18:15:11'
ryu1_IP = '10.0.0.100'

scaling_MAC = '02:0a:12:14:0c:05'

lb_socket = conf.L2socket(iface=active_interface)

# Format is {id:piid_ip}
piid_ids = {}
# Format is {piid_ip:{(ip_src,ip_dst,tcp_src,tcp_dst):flow_rate,...},...}
piid_tcp_assign={}

# An estimate of the maximum data rate a PIID instance can accomodate
capacity = None 
allowance = 10000

# If dport is 2021, send a hello packet
# Otherwise, send a flow installation request packet
def send_to_controller(dport=2021,req_str=None):
	global ryu1_MAC
	global ryu1_IP
	global load_balancer_MAC
	global load_balancer_IP
	global lb_socket
	eth = Ether(src=load_balancer_MAC,dst=ryu1_MAC)
	ip = IP(src=load_balancer_IP,dst=ryu1_IP)
	udp = UDP(dport=dport)
	pkt = eth/ip/udp
	if req_str!=None:
		pkt = pkt/req_str
	lb_socket.send(pkt)	

# The goal of this function is to balance the tcp flows among instances in an attempt to prevent overloading
# update capacity will only be set when a piid instance was found to have cpu_util>= MAX_THRESHOLD 
def load_balance(update_capacity=0):
	global piid_tcp_assign
	global capacity
	global allowance
	piid_flowrate={}
	# Create a list of piid instance to total tcp flow rate
	# The total tcp flow rate of a piid instance will serve as it weight for balancing
	for piid in piid_tcp_assign:
		piid_flowrate[piid]=sum(piid_tcp_assign[piid].values())
	# The request string will contain all the necessary flow redirections to be performed
	req_str = ""
	print("Current State: ",str(piid_tcp_assign),"\n")
	while True:
		sorted_piid_flowrate = sorted(piid_flowrate.items(),key=lambda kv: kv[1])
		most_loaded_piid = sorted_piid_flowrate[-1][0]
		most_loaded_piid_rate = sorted_piid_flowrate[-1][1]
		if update_capacity:
			capacity = most_loaded_piid_rate
			update_capacity = 0
		# Estimate whether the most loaded piid will soon be overloaded (or cpu_util>=MAX_THRESHOLD)
		if most_loaded_piid_rate + allowance >= capacity: 
			largest_tcp_flow = max(piid_tcp_assign[most_loaded_piid],key=piid_tcp_assign[most_loaded_piid].get)
			largest_tcp_flow_rate = piid_tcp_assign[most_loaded_piid][largest_tcp_flow]
			least_loaded_piid = sorted_piid_flowrate[0][0]
			least_loaded_piid_rate = sorted_piid_flowrate[0][1]	
			# If so, attempt to redirect its largest flow to the least loaded piid  
			# It would be useless to transfer a flow if least_loaded_piid_rate + largest_tcp_flow_rate = most_loaded_piid_rate
			# Requirement: least_loaded_piid_rate + largest_tcp_flow_rate <<< most_loaded_piid_rate
			if least_loaded_piid_rate + largest_tcp_flow_rate + allowance < most_loaded_piid_rate:
				# Transfer largest_tcp_flow from the most_loaded_piid to least_loaded_piid
				piid_tcp_assign[least_loaded_piid][largest_tcp_flow] = piid_tcp_assign[most_loaded_piid].pop(largest_tcp_flow)
				# Update the total tcp flow rate of the two instances
				piid_flowrate[most_loaded_piid]-=largest_tcp_flow_rate
				piid_flowrate[least_loaded_piid]+=largest_tcp_flow_rate
				# Append the new assignment to the request
				if len(req_str)>0:
					req_str+=";"
				req_str+=str(largest_tcp_flow)+"-"+least_loaded_piid+"-"+most_loaded_piid
			# The least loaded piid cannot accomodate the largest flow of the most loaded piid, can't do anything
			# No means of lessening the load of the most loaded instance
			else:
				break
		# The most loaded piid is unlikely to be overloaded so, no need to lessen its load		
		else:
			break
		print("Capacity: ",capacity,"\n")
		print("piid_flowrate: ",str(piid_flowrate),"\n")
		print("Load Balancing Step: ",req_str,"\n")
	if len(req_str)>0:
		send_to_controller(2222,req_str)		
		print("[Timestamp]:",(datetime.datetime.now()-start_time).total_seconds(),"---Load balancing Done\n")
		print(req_str,"\n")

# This function is triggered whenever a piid instance is found to have a cpu_util<=MIN_THRESHOLD
# Hence, we will attempt to redistribute the flows (assigned to the least loaded piid instance) among the other instances
def redistribute(under_loaded_piid):
	global piid_tcp_assign
	global capacity
	global allowance
	piid_flowrate={}
	# Create a list of piid instance to total tcp flow rate
	# The total tcp flow rate of a piid instance will serve as its weight for balancing
	for piid in piid_tcp_assign:
		piid_flowrate[piid]=sum(piid_tcp_assign[piid].values())

	#under_loaded_piid = min(piid_flowrate,key=piid_flowrate.get)
	piid_flowrate.pop(under_loaded_piid)
	# Sort the tcp flows to be redistributed in descending order 
	desc_sorted_tcp_flows = sorted(piid_tcp_assign[under_loaded_piid].items(),key=lambda kv: kv[1])[::-1]
	new_assignment = {}
	print("Capacity: ",capacity,"\n")
	print("piid_flowrate: ",piid_flowrate,"\n")

	complete_distribution = 1
	for flow in desc_sorted_tcp_flows:
		least_loaded_piid = min(piid_flowrate,key=piid_flowrate.get)
		least_loaded_piid_rate = piid_flowrate[least_loaded_piid]
		if least_loaded_piid_rate + flow[1] + allowance < capacity:
			new_assignment[flow[0]] = least_loaded_piid
			piid_flowrate[least_loaded_piid] += flow[1]
		else:
			print("Redistribution not possible\n")
			complete_distribution = 0
			break
		print("Redistribution Step: ",str(new_assignment),"\n")	
		print("piid_flowrate: ",piid_flowrate,"\n")
	# The request string will contain all the necessary flow redirections to be performed
	if complete_distribution:
		req_str = ""
		for flow in new_assignment:
			piid = new_assignment[flow]
			piid_tcp_assign[piid][flow]=piid_tcp_assign[under_loaded_piid].pop(flow)
			if len(req_str)>0:
				req_str+=";"
			req_str+=str(flow)+"-"+piid+"-"+under_loaded_piid
		piid_tcp_assign.pop(under_loaded_piid)
		send_to_controller(2222,req_str)	
		print("[Timestamp]:",(datetime.datetime.now()-start_time).total_seconds(),"---Redistribution Done\n")
		print(req_str,"\n")	


def process_packet(packet):
	global piid_tcp_assign
	global piid_ids
	global lb_socket
	global start_time
	global load_balancer_MAC
	global capacity

	if packet[Ether].src==load_balancer_MAC:
		return

	# Discover a new tcp flow 
	# After obtaining the tcp flow information, forward the packet to the server
	# Case 1: Choose a PIID vnf to process the packets from the tcp flow
	if TCP in packet:
		print("[Event]: Received TCP Packet\n")

		if start_time==None:
			# Relative timestamps with respect to the first TCP SYN packet sent by the client
			start_time = datetime.datetime.now()

		# Extract flow information from the packet
		new_tcp_flow = (packet[IP].src,packet[IP].dst,packet[TCP].sport,packet[TCP].dport)
		# Forward the tcp packet
		lb_socket.send(Ether(src=load_balancer_MAC,dst=packet[Ether].dst)/packet[IP])

		# If the load balancer is already aware of a PIID instance, assignment can follow.
		if len(piid_tcp_assign)>0:
			tcp_flows = []
			for piid in piid_tcp_assign:
				tcp_flows+=piid_tcp_assign[piid].keys()

			if new_tcp_flow not in tcp_flows:
				print("[Event]: New TCP Flow\n")
				print("[Timestamp]:",(datetime.datetime.now()-start_time).total_seconds(),"---New TCP Flow\n")
				# Determine the least loaded PIID instance
				piid_flowrate={}
				for piid in piid_tcp_assign:
					piid_flowrate[piid]=sum(piid_tcp_assign[piid].values())
				least_loaded_piid = min(piid_flowrate,key=piid_flowrate.get)
				piid_tcp_assign[least_loaded_piid][new_tcp_flow]=0
				# Send a flow installation request packet
				req_str = str(new_tcp_flow)+"-"+least_loaded_piid
				send_to_controller(2222,req_str)
				# print("Assignment:",piid_tcp_assign,"\n")

	elif UDP in packet:
		# A TCP flowrate report from the controller obtained by periodically querying the switches
		if packet[Ether].src == ryu1_MAC:
			print("[Event]: Received FlowStats report from controller\n")
			# Parse the udp payload to obtain the byte rate of each TCP flow
			flowrate_report = eval(packet[Raw].load.decode('ISO-8859-1'))
			print("FlowStats Report:",flowrate_report,"\n")
			# Update the data rate of each TCP flow 
			for piid in piid_tcp_assign:
				for tcp_flow in piid_tcp_assign[piid]:
					if tcp_flow in flowrate_report:
						piid_tcp_assign[piid][tcp_flow]=flowrate_report[tcp_flow]
			# Perform balancing to prevent overloading 
			#if capacity!=None:
			#	load_balance()

		# A hello packet from a new PIID instance				
		# If a hello packet was received and there are already existing PIID vnf instances,
		# it means that a new PIID instance was created because some PIID instance is being overutilized
		# tcp flow reassignment must be performed
		# Otherwise, the hello packet is from the first PIID instance. 
		elif packet[UDP].dport == 2020:
			print("[Event]: Received Hello packet from a PIID instance\n")
			new_piid = packet[Ether].src
			piid_tcp_assign[new_piid] = {}
			piid_ids[len(piid_tcp_assign)]=new_piid
			#print packet.show(),"\n"
			if len(piid_tcp_assign)>1:
				print("[Event]: The hello packet is a load balancing request packet!\n")
				load_balance(1)

		# A packet sent by the scaling script
		elif packet[Ether].dst==scaling_MAC:
			payload = packet[Raw].load.decode('ISO-8859-1')
			if "overload" in payload:
				load_balance(1)
			elif "underload" in payload:
				under_loaded_piid_id = int(payload.split(':')[1])
				under_loaded_piid = piid_ids[under_loaded_piid_id]
				if under_loaded_piid in piid_tcp_assign:
					redistribute(under_loaded_piid)


#threading.Timer(1,send_to_controller).start()	
send_to_controller()
sniff(prn=process_packet,filter='(tcp and net 192.168.100.0/24) or udp',store=0)
