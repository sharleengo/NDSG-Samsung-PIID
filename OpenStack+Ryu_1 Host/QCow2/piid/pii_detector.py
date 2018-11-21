from scapy.all import *
from country_list import countries_for_language
import socket
import re

# connection variables
active_interface = [intf for intf in get_if_list() if "e" in intf][0]
piid_MAC = get_if_hwaddr(active_interface)
piid_IP = os.popen('ip addr show '+active_interface).read().split("inet ")[1].split("/")[0]

ryu1_MAC = '03:14:20:18:15:11'
ryu1_IP = '10.0.0.100'

ryu2_MAC = '03:14:20:18:15:12'
ryu2_IP = '192.168.100.100'

piid_socket = conf.L2socket(iface=active_interface)
                       
pii_count = 0

#PII Categories

AGE_RANGE_REGEX = re.compile(r"^[0-9]{1,3}-[0-9]{1,3}$") # where the second number is larger than the first

EMAIL_REGEX = re.compile(r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)")

GEO_REGEX = re.compile(r"^[\+\-]{0,1}\d+\.\d{4}\d+$") # where the valuse is within the range of the country

GENDER_REGEX = re.compile(r"^[mf]$") 
GENDER_REGEX_2 = re.compile(r"^(fe)?male$") # or the corresponding words for male/female in local language

PHONE_REGEX = re.compile(r"^([+]code)?((38[{8,9}|0])|(34[{7-9}|0])|(36[6|8|0])|(33[{3-9}|0])|32[{8,9}\))([\d]{7})$")

POSTAL_CODE_REGEX = re.compile(r"^\d{5}$")

COUNTRY_LIST = dict(countries_for_language('en'))

def is_PII(string):
	if AGE_RANGE_REGEX.match(string):
		arange = string.split("-")
		if int(arange[0])<int(arange[1]):
			return "Age Range"
		else:
			return False
	elif EMAIL_REGEX.match(string):
		return "Email"
	elif GEO_REGEX.match(string):
		return "Geo"
	elif GENDER_REGEX.match(string) or GENDER_REGEX_2.match(string):
		return "Gender"
	elif PHONE_REGEX.match(string):
		return "Phone Number"
	elif POSTAL_CODE_REGEX.match(string):
		return "Postal Code"
	elif string in COUNTRY_LIST or string in COUNTRY_LIST.values():
		return "Country"
	else:
		return False

def process_tcp_packet(packet):

	# Ignore outgoing packets (already forwarded to the sink or controller)
	if packet[Ether].src ==piid_MAC:
		return

	global piid_socket
	global pii_count
	domain = None

	if Raw in packet:
		payload=packet[Raw].load.decode('ISO-8859-1')
		for fields in payload.split('\r\n'):
			field_contents = fields.split(" ")
			if  field_contents[0]=="Host:":
				domain = field_contents[1]
			elif len(field_contents)>1:
				s = field_contents[1]
				if '?' in s:
					s=s[s.index('?')+1:]
				for kv in s.split("&"):
					pair = kv.split("=")	
					if len(pair)==2:
						value_is_PII = is_PII(pair[1])
						if value_is_PII:
							pii_count+=1
							print("Key:",pair[0],"Value:",pair[1],"PII Type:",value_is_PII,"\n")
							print("# packets with PII:",pii_count,"\n\n")
							piid_socket.send(Ether(src=piid_MAC,dst=packet[Ether].dst)/packet[IP])
							# Send the PII-containing packet to the controller to trigger flow installation
							#piid_socket.send(Ether(src=piid_MAC,dst=ryu2_MAC)/packet[IP])
							return
							
	piid_socket.send(Ether(src=piid_MAC,dst=packet[Ether].dst)/packet[IP])

hello_pkt = Ether(src=piid_MAC,dst=ryu1_MAC)/IP(src=piid_IP,dst=ryu1_IP)/UDP(dport=2020)
piid_socket.send(hello_pkt)		
sniff(iface=active_interface, prn=process_tcp_packet, filter='tcp', store=0)
