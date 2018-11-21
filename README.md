# NDSG-Samsung-PIID
A Personally Identifiable Information (PII) detector system implemented by leveraging an SDN/NFV-based architecture with Ryu as the SDN controller, OpenStack as the NFVI and VIM, and OpenSource Mano as the NFV Orchestrator and VNF Manager. 
- - - -
### Initial Configurations ###
* For all machines, the base iso image is Ubuntu 16.04: http://releases.ubuntu.com/16.04/
* In the **OpenStack machine**:
1. Download the latest stable version of devstack (https://docs.openstack.org/devstack/latest/) with ceilometer and gnocchi components
    * ```sudo useradd -s /bin/bash -d /opt/stack -m stack```
	* ```echo "stack ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/stack```
	* ```sudo su - stack```
	* ```git clone https://git.openstack.org/openstack-dev/devstack -b stable/rocky```
	* ```cd devstack```
	* copy the **local.conf** file from the **OpenStack+Ryu_1 Host** folder into the devstack directory
	* ```./stack.sh```
2. After the installation, set the OpenStack IP address as a static IP address for the machine.
    * So that later on, this IP address will be preserved when it is connected to the Zodiac GX switch and disconnected from the Internet
3. In OpenStack, choose a project and create a topology consisting of a router connecting a public network and private network.	
4. Upload the qcow2 images for the PII detector and Load Balancer VNFs (found in **OpenStack+Ryu_1 Host/QCow2**) in glance. 

* In the **OSM machine**:
1. Download the pre-release of OSM version 5 (https://osm-download.etsi.org/ftp/osm-4.0-four/4th-hackfest/presentations/20181101%20OSM%20Hackfest%20-%20Session%206%20-%20OSM%20Fault%20&%20Performance%20Management.pdf)
    * ```git clone https://osm.etsi.org/gerrit/osm/devops```
	* ```./devops/installers/full_install_osm.sh --test -b master```
2. Visit the OSM UI and create a vim referencing the OpenStack host:
    * Make sure that during this step, the OpenStack and OSM machines are connected to the same network. 
   * Sample configuration variables:
		* Name:	LOCAL_openstack
		* VIM Username:	admin
		* VIM URL:	http://192.168.100.78/identity/v3
		* Type:	openstack
		* Tenant name:	demo
3. Onboard the PII detector and Load Balancer vnfds provided in **OSM+Ryu_2 Host/VNFD** 
4. Onboard the base_nsd (consisting of a single load balancer vnf) and piid-nsd vnfs (consisting of a single PII detector vnf) provided in **OSM+Ryu_2 Host/NSD**
    * The reason as to why the two vnfs are in separate ns is to enable the scaling down mechanism to delete any piid instance through the ns-delete command (and likewise, to prevent the deletion of the load balancer instance) 
4. Set the OSM IP address as a static IP address for the machine.

* In the **Mininet machine:**
1. Download Mininet (native installation: http://mininet.org/download/)
    * ```git clone git://github.com/mininet/mininet```
	* ```cd mininet```
	* ```git tag  # list available versions```
	* ```git checkout -b 2.2.1 2.2.1  # or whatever version you wish to install```
	* ```cd ..```
	* ```mininet/util/install.sh -a```
2. Install tshark
    * ```sudo add-apt-repository ppa:wireshark-dev/stable```
	* ```sudo apt-get install wireshark```
	* ```sudo apt-get install tshark```

* In the **Zodiac GX SDN switch:**
1.	Set the controller’s IP address to the OSM machine's IP address and a chosen port number (in my case, 6633)
- - - -
### Setup for running experiments: ###
1. In the **OpenStack machine**, run the ```start_ryu.sh``` script found in **OpenStack+Ryu_1 Host**.
    * This command performs the following steps:
     1. Creates an additional port in ```br-ex``` to be connected to the physical interface
     2. In ```br-ex```, deletes the flow (installed by Neutron) which drops all packets with ```in_port="phy-br-ex"``` (else, processed packets will never exit the OpenStack cluster)
    3. Runs ```ryu-manager --verbose ryu_controller_1.py --ofp-tcp-listen-port 6653```
    4. ```ryu_controller_1.py``` installs a flow such that all packets with ```dst_mac=RYU1_MAC``` are forwarded to the controller. ( so that the controller can obtain the discovery packets sent by the load balancer and piid instances )
2. In the OSM machine, make sure that your MON container matches the metrics granularity of the underlying VIM. 
    * Run ```docker service update --env-add OS_DEFAULT_GRAMULARITY=< gnnochi granularity defined in /etc/ceilometer/polling.yaml file in OpenStack> osm_mon```
3. Run ```ryu-manager --verbose ryu_controller_2.py --ofp-tcp-listen-port 6633```
    * ```ryu_controller_2.py``` installs the following flows:
     1. A match-all flow to forward packets to the controller (so that under normal circumstances, it acts like a learning switch)
     2. A flow such that packets from the port connected to the Mininet host with ```src_ip=CLIENT_IP``` and ```dst_ip=SERVER_IP``` are forwarded to the port connected to the OpenStack cluster
     3. A flow such that packets from the port connected to the OpenStack cluster with ```src_ip=CLIENT_IP``` and ```dst_ip=SERVER_IP``` are forwarded to the port connected to the Mininet host
     4. A flow such that packets with ```dst_mac=RYU2_MAC``` are forwarded to the controller. ( so that packets containing PII are forwarded to the controller, triggering flow installation to block the PII-leaking flow)
4. To enable scaling, also run ```scaling.py``` in the OSM Host
    * The IP addresses of the OSM and OpenStack Host are hardcoded in scaling.py to enable signaling communication between the scaling script and the load balancer vnf, so make sure to correctly configure these values.
5. Instantiate a base-ns and piid-ns instance via OSM:
    * ```osm ns-create --ns_name LB --nsd_name base-ns --vim_account LOCAL_openstack --config '{ vld : [ { name: mgmt-vl, vim-network-name: <name of the private network created in OpenStack>} ] }' ```
   * ```osm ns-create --ns_name P1 --nsd_name piid-ns --vim_account LOCAL_openstack --config '{ vld : [ { name: mgmt-vl, vim-network-name: <name of the private network created in OpenStack>} ] }' ```
6. 	Once the load balancer and PII detector instances have started and metrics are being displayed by the scaling script, the experient can begin. In the Mininet host, run ```2host_topo.py```.
    * ```2host_topo.py``` performs the following steps:
     1. Constructs a topology consisting of 2 Mininet hosts: client and server
     2. Creates an additional port in the switch to be connected to the physical interface
     3. Installs flows in the switch such that HTTP packets from the client are sent out to the physical interface and incoming packets (destined to the server) from the physical interface are forwarded to the server.
     4. Configures static IP addresses for the client and server such that they lie in the same subnet as the OpenStack and OSM machines.
     5. Starts the server - listens for client connections and sends out SYNACKs and ACKs
     6. Every 5 or 10 mins, introduces or terminates HTTP flows with differing rates originating from the client.
     7. During the experiment, packet capture using tshark also runs. These tracefiles from client and server are used to measure the latency, packet loss and throughput of each flow.
