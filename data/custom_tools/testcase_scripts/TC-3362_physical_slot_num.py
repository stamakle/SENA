import os
import logging
import json
from datetime import datetime
from pprint import pformat
import socket
import argparse
import subprocess

parser = argparse.ArgumentParser(description="link speed change retrain test script")
parser.add_argument("--log-folder", type=str, help="path to store log files", default=None)

options = parser.parse_args()
HOSTNAME = socket.gethostname()

script = os.path.basename(__file__).rsplit(".")[0]
date_string = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
if options.log_folder:
    logs = os.path.join(options.log_folder, HOSTNAME)
else:
    logs = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(f"{logs}", exist_ok=True)
logFile = os.path.join(logs, f'{script}_{date_string}.log')

# configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(filename)s, %(lineno)d] [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(logFile),
        logging.StreamHandler()
    ]
)

MSECLI = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'msecli')
DIRVES_JSON = logFile.replace('.log', '.json')
dutDict = dict()
dutDevice = dict()
dutCap = dict()
dutSN = dict()
output = os.popen(f'{MSECLI} -L').readlines()
for line in output:
    if 'Device Name' in line and 'boss' not in line:
        dut_path = line.rsplit(":")[-1].rstrip()
        try:
            cmd = f'{MSECLI} -L -J -n {dut_path}'
            json_data = json.loads(os.popen(cmd).read())
            #logging.info(f"====== {dut_path} =====\n{pformat(json_data)}")
            for line in json_data['drives']:
                dut_path = line['deviceName']
                dut_sn = line['serialNumber']
                dut_model = line['modelNumber']
                dut_pciePath = line['pciInfo']['pciPATH'].lower()
                dut_cap = line['driveDensityGB']
                if 'false' in line['bootDrive']:
                    cmd = 'ls -la /sys/class/nvme/*'
                    output = os.popen(cmd).readlines()
                    for line in output:
                        if dut_pciePath in line:
                            parentPath = line.rsplit('/')[-4].replace('0000:', '')
                            #logging.info(
                                #f"dut: {dut_path}, sn: {dut_sn}, model: {dut_model}, parent Path: {parentPath}, end Path: {dut_pciePath}")
                            dutDict[dut_pciePath] = parentPath
                            dutDevice[dut_pciePath] = dut_path
                            dutCap[dut_pciePath] = dut_cap
                            dutSN[dut_pciePath] = dut_sn

        except Exception as e:
            print(e)


def physical_slot_verify():

    logging.info('=========================================================')
    logging.info('TC-3362: Physical Slot Number Parameter')
    logging.info('=========================================================')
        
    for USP, DSP in dutDict.items():
        
        #power_scale = {'0b00': '1.0x','0b01': '0.1x', '0b10': '0.01x', '0b11':'0.001x'}
        command = ['sudo', 'setpci', '-s', DSP, 'CAP_EXP+14.L']
        register_readout= int(subprocess.check_output(command).strip(), 16)
        logging.info(f'---PCI Register at {DSP}, slot capabilities: {hex(register_readout)}')
    
        register_binary = bin(int(hex(register_readout),16))
     
        
        if len(register_binary) == 34:
            slot_cap = register_binary[2:]
        else: 
            slot_cap = register_binary[2:].zfill(32)
        
        Bit_31_to_27 = slot_cap[0:5]
        Bit_26 = slot_cap[5]
        Bay_ID = slot_cap[6:8]
        Slot_ID = slot_cap[8:13]
    
        logging.info(f'Bit31:27 for {DSP}, {USP} = ' + '0b'+ Bit_31_to_27)
        logging.info(f'Bit26 for {DSP}, {USP} = ' + '0b'+ Bit_26)
        logging.info(f'BayID for {DSP}, {USP} = ' + '0b'+Bay_ID + ', Bay# ' + str(int('0b'+Bay_ID,2)))
        logging.info(f'SlotID for {DSP}, {USP} =' + '0b'+Slot_ID+ ', Physical Slot# ' + str(int('0b'+Slot_ID,2)))
        
physical_slot_verify()