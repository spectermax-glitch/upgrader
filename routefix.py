#!venv/bin/python
# This is to update the default route on a sensor that is unable to connect to tailscale.
# it requires a secret password 
import sys
import requests
import json
from subprocess import run
from qadmin import *
from pathlib import Path
import os
from time import sleep
from getpass import getpass


SECRET_PATH = Path.home() / "secrets" / "ssh"
if os.environ.get('SSHPASS') == None:
    if SECRET_PATH.exists():
        os.environ['SSHPASS'] = open(SECRET_PATH).read().strip()
    else:
        print("This utility requires the ssh password.")
        os.environ['SSHPASS'] = getpass("Enter ssh password: ")


qa = QAdmin()
devnull = open('/dev/null', 'w+')

def mn_peer_query(mothernode):
    result = requests.get(f'http://{mothernode}:8090/api/v1/peer-query')
    return result.json()['discovered_peers']

def get_mn_peers(mothernode):
    peers = mn_peer_query(mothernode)
    assets = {}
    for peer in peers:
        asset_id = peer['asset_id']['id']
        ip = peer['presence']['addresses'][0]['ip']['V4']['v4']
        assets[asset_id] = ip
    return assets

def ping(host, timeout=3):
    proc = run(['ping', f'-W{timeout}', '-c1', host], stdout=devnull, stderr=devnull)
    if proc.returncode == 0:
        return True
    else:
        return False

def exec_thru_mn(mothernode, local_ip, command):
    with open('/dev/null', 'w+') as devnull:
        proc = run(f"sshpass -e ssh -J specter@{mothernode} specter@{local_ip} \"{command}\"", shell=True, capture_output=True)
    result = proc.stdout.decode()
    return result

def get_default_routes(mothernode, local_ip):
    default_routes = []
    result = exec_thru_mn(mothernode, local_ip, "ip r")
    for line in result.splitlines():
        if 'default' in line:
            print(line)
            parts = line.split()
            cost = parts[-1]
            dev = parts[parts.index('dev') + 1]
            if 'via' in parts:
                gateway = parts[parts.index('via') + 1]
            else:
                gateway = dev
            default_routes.append((gateway, dev, cost))
    sorted_routes = sorted(default_routes, key=lambda x:x[2])
    return sorted_routes

def whodis(host):
    result = requests.get(f"http://{host}:7878/")
    return result.json()            

def get_local_ip(host):
    info = whodis(host)
    interfaces = info['ip_addresses']
    for interface in interfaces:
        if '192.168.13' in interface['address']:
            return interface['address'].split('/')[0]

def get_remote_local_interface(jumphost, host):
    proc = run(f'sshpass -e ssh specter@{jumphost} "curl http://{host}:7878/"', shell=True, capture_output=True)
    result = json.loads(proc.stdout.decode())
    ip_addresses = result['ip_addresses']
    print(ip_addresses)
    interfaces = []
    for interface in ip_addresses:
#        print(interface)
        dev = interface['interface']
        ip = interface['address'].split('/')[0]
        if '192.168.13.' in ip:
            interfaces.append({"dev": dev, "ip": ip})
    if len(interfaces) > 1:
        print(interfaces)
        raise Exception(f'Multiple interfaces on 192.168.13.x!')
    else:
        return interfaces[0]

def set_default_route(aid):
    sensor = f"sensor-node-{aid}"
    if ping(sensor):
        print("Host is responding")
        exit()
    mothernode_tailscale_ip = qa.mothernode_ip(aid)
    print('fetching peers')
    peers = get_mn_peers(mothernode_tailscale_ip)
    if aid in peers:
        print('sensor may be reachable via mothernode')
        sensor_local_ip = peers[aid]
        print('fetching default routes')
        routes = get_default_routes(mothernode_tailscale_ip, sensor_local_ip)
#        print(routes)
        print('gathering remote interfaces')
        local_interface = get_remote_local_interface(mothernode_tailscale_ip, sensor_local_ip)
        sensor_local_device = local_interface['dev']
        sensor_interface_ip = local_interface['ip']
        if sensor_interface_ip != sensor_local_ip:
            raise Exception(f"IP Mismatch {local_ip}<->{interface_ip}")
#        print(f"remote interface: {local_device} {interface_ip}")
        mothernode_local_ip = get_local_ip(mothernode_tailscale_ip)
        command = f'sudo ip route add default via {mothernode_local_ip} dev {sensor_local_device} metric 10'
        print('\n' + command)
        yorn = input('Execute command? ')
        if yorn.strip() in ['y', 'Y', 'yes', 'Yes', 'yeah', 'ok']:
            print('setting default route')
            result = exec_thru_mn(mothernode_tailscale_ip, sensor_local_ip, command)            
            print(result)
        else:
            print('quitting')
            sys.exit(0)
        print('default route set')
        print('pausing for route to take effect')
        c = 0
        while c < 3:
            sleep(3)
            if ping(f"sensor-node-{aid}"):
                print('Host is responding to ping!')
                sys.exit(0)
            else:
                print('Still no ping...')
                c += 1
        print('It could take a few minutes for the device to reconnect to tailscale.')


if __name__ == "__main__":
    asset_input = sys.argv[1]
    if asset_input.startswith('sensor-node-'):
        aid = int(re.findall(r'^.*?-([0-9]{4})$', asset_input))
    else:
        aid = int(asset_input)
    set_default_route(aid) 

