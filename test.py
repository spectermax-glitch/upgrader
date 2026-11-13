import sys
import re

if __name__ == "__main__":
    target = sys.argv[1]
    if target.startswith('sensor-node-'):
        sensor_name = target
        sensor_aid = int(re.findall(r'^sensor-node-([0-9]{4})', sensor_name)[0])
    elif re.match(r'[0-9]{4}', target):
        sensor_name = f"sensor-node-{target}"
        sensor_aid = int(target)
    print(sensor_name, sensor_aid)
