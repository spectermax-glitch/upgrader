#!/usr/bin/env python3
import sys
from subprocess import run



target="$1"
if [[ ! $target =~ ^sensor-node ]]; then
  target="sensor-node-${target}"
fi
echo "upgrading ${target}"
ping -c1 -W3 ${target} &>/dev/null
if [ $? -ne 0 ]; then
  echo "${target} not responding to ping"
  exit
fi
THASH="$(git -C $(pwd) rev-parse HEAD)"

manifest="$(curl -s ${target}:7878)"
SHASH=$(echo "${manifest}" | grep staged_system | awk '{print $2}' | tr -d [,\"])
RHASH=$(echo "${manifest}" | grep running_system | awk '{print $2}' | tr -d [,\"])
board=$(echo "${manifest}" | grep specter, | awk -F"," '{print $2}' | tr -d \" |sed "s/sensor-node/sensornode/g")

echo "target hash : ${THASH}"
echo "running hash: ${RHASH}"
if [ $THASH == $RHASH ]; then
	echo "Already running desired release"
	exit
elif [ $THASH == $SHASH ]; then
	echo "staged hash : ${SHASH}"
	echo "Rebooting to new release"
	ssh specter@${target} "sudo reboot"
        exit	
fi

echo "Upgrading ${target}"
nixos-rebuild boot --flake .#${board} --use-remote-sudo --target-host specter@${target} --show-trace
"$0" "$@"


if __name__ == "__main__":
    target = sys.argv[1]
    if target.startswith('sensor-node-'):
        sensor_name = target
        sensor_aid = int(re.findall(r'^sensor-node-([0-9]{4})', sensor_name)[0])
    elif re.match(r'[0-9]{4}', target):
        sensor-name = f"sensor-node-{target}"
        sensor_aid = int(target)
    if ping(sensor-name):
        upgrade(sensor_aid)
    else:
        print('could not ping sensor.')
        try:
            set_default_route(sensor_aid)
        except Exception as e:
            print('failed to fix route: {e}')
            sys.exit()
         
