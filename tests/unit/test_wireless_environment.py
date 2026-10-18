"""Radio evidence must not turn missing driver counters into a clean channel."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from framework.wireless_environment import survey, busy_fraction, interfaces, remote


def test_only_active_channel_and_counter_deltas():
    text="""Survey data from wlan0
 frequency: 2412 MHz [in use]
 noise: -95 dBm
 channel active time: 1000 ms
 channel busy time: 50 ms
Survey data from wlan0
 frequency: 2437 MHz
 channel active time: 2000 ms
 channel busy time: 1800 ms
"""
    a=survey(text);b=survey(text.replace('1000 ms','2000 ms').replace('50 ms','150 ms'))
    assert a['frequency_mhz']==2412 and a['noise_dbm']==-95
    assert busy_fraction(a,b)==.1
    assert busy_fraction(b,a) is None
    assert busy_fraction(a,dict(b,frequency_mhz=2437)) is None
    assert busy_fraction(a,dict(b,busy_ms=None)) is None
    assert busy_fraction(a,dict(b,busy_ms=99999)) is None


def test_missing_and_ambiguous_driver_output_is_unavailable():
    assert survey('command not found')['status']=='unavailable'
    assert survey('Survey data from x [in use] Survey data from y [in use]')['status']=='unavailable'
    assert interfaces('Interface wlan0',' ath0: 0000 -45')==['ath0','wlan0']
    assert interfaces('Interface wlan0; reboot','')==[]
    with pytest.raises(ValueError):remote('-oProxyCommand=bad','iw dev')



def test_unifi_disabled_fields_and_native_units_are_not_relabelled():
    from framework.wireless_environment import unifi_stats, unifi_channel
    text="""Radio Level Stats: wifi0
Channel Utilization (0-255) = <DISABLED>
Rx RSSI = 66
Rx CRC errors = 120
Best effort = 4
Best effort = 5
"""
    values=unifi_stats(text,'radio','wifi0')
    assert values['status']=='available'
    assert values['fields']['Channel Utilization (0-255)'] is None
    assert values['fields']['Rx RSSI']==66
    assert values['fields']['Best effort'] is None
    assert unifi_stats(text,'radio','wifi1')['status']=='unavailable'
    assert unifi_stats('station not found','station','40:82:7b:02:60:0a')['status']=='unavailable'
    assert unifi_channel('Current Frequency:2.437 GHz (Channel 6)')==dict(frequency_mhz=2437,channel=6)
    assert unifi_channel('Channel 06 : 2.437 GHz') is None


def test_unifi_arguments_cannot_inject_remote_commands(tmp_path):
    from framework.wireless_environment import collect
    with pytest.raises(ValueError):
        collect('test',tmp_path/'bad',backend='unifi',radio='wifi0; reboot',
                interface='wifi0ap2',station='40:82:7b:02:60:0a')
    assert not (tmp_path/'bad').exists()
