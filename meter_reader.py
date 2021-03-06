#!/usr/bin/python
'''Script to read utility meter transmissions and post the rate of change 
in meter reading (reading change per hour) at a specified interval.  Values 
are posted to the 'readings/final/rtlamr' topic on the MQTT broker running 
on localhost.

This script assumes the RTL-SDR Software Defined Radio is based on R820T2 tuner and 
RTL2832U chips.

This script assumes that the program rtl_tcp is already running. (I tried starting
it within this script, but it then captured keystrokes such as Ctrl-C.).

This script has a number of relevant values in the Mini-Monitor settings file:
    LOGGER_ID = The base sensor ID string that is prepended to the Meter ID
        to form the final Sensor ID.  This setting is used by the pi_logger.py
        script as well as this one.
    ENABLE_METER_READER = True or False, determining whether this script runs.
    METER_IDS = A Python list indicating those meter IDs to record and post.
    METER_POST_INTERVAL = Minutes between posting of the meter reading change.
    METER_MULT = A multiplier to apply to the meter change rate before posting
        to the MQTT broker.
'''
import subprocess
import signal
import sys
import time
import logging
import mqtt_poster
import config_logging

# Configure logging and log a restart of the app
config_logging.configure_logging(logging, '/var/log/meter_reader.log')
logging.warning('meter_reader has restarted')

# The settings file is installed in the FAT boot partition of the Pi SD card,
# so that it can be easily configured from the PC that creates the SD card.  
# Include that directory in the Path so the settings file can be found.
sys.path.insert(0, '/boot/pi_logger')
import settings

def shutdown(signum, frame):
    '''Kills the external processes that were started by this script
    '''
    rtlamr.kill()
    sys.exit(0)

# If process is being killed, go through shutdown process
signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

# Dictionary keyed on Meter ID that holds the last 
# reading that caused a post to the MQTT broker.
last_reads = {}

def get_last(meter_id):
    """Returns a (ts, val) tuple for Meter ID 'meter_id'.  If that 
    Meter ID is not present (None, None) is returned.
    """
    return last_reads.get(meter_id, (None, None))

def set_last(meter_id, ts, val):
    """Sets the last meter reading for Meter ID 'meter_id'.
    The attributes stored are the timestamp 'ts' and the
    value 'val'.
    """
    last_reads[meter_id] = (ts, val)

# Start up the object that will post the final readings to the MQTT
# broker.
mqtt = mqtt_poster.MQTTposter()
mqtt.start()

# start the rtlamr program.
rtlamr = subprocess.Popen(['/home/pi/gocode/bin/rtlamr', 
    '-gainbyindex=24',   # index 24 was found to be the most sensitive
    '-format=csv'], stdout=subprocess.PIPE)

while True:

    try:
        flds = rtlamr.stdout.readline().strip().split(',')

        if len(flds) != 9:
            # valid readings have nine fields
            continue

        # If the list of Meter IDs to record is not empty, make sure this ID
        # is in the list of IDs to record.
        meter_id = int(flds[3])
        if len(settings.METER_IDS) and meter_id not in settings.METER_IDS:
            continue

        ts_cur = time.time()
        read_cur = float(flds[7])
        logging.debug('%s %s %s' % (ts_cur, meter_id, read_cur))

        ts_last, read_last = get_last(meter_id)
        if ts_last is None:
            set_last(meter_id, ts_cur, read_cur)
            continue

        if ts_cur > ts_last + settings.METER_POST_INTERVAL * 60.0:
            # enough time has elapsed to make a post.  calculate the
            # rate of meter reading change per hour.
            rate = (read_cur - read_last) * 3600.0 * getattr(settings, 'METER_MULT', 1.0) / (ts_cur - ts_last)
            
            # time stamp in the middle of the reading period
            ts_post = (ts_cur + ts_last) / 2.0

            mqtt.publish('readings/final/meter_reader', '%s\t%s_%s\t%s' % (int(ts_post), settings.LOGGER_ID, meter_id, rate) )
            set_last(meter_id, ts_cur, read_cur)

    except:
        logging.exception('Error processing reading %s' % flds)
        time.sleep(2)
