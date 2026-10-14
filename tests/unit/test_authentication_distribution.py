import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from framework.authentication_distribution import box

def test_tukey_whiskers_do_not_hide_extreme_points():
    s=box([1,2,3,4,5,100])
    assert s['q1']==2.25 and s['median']==3.5 and s['q3']==4.75
    assert s['upper']==5 and s['maximum']==100 and s['n']==6

def test_constant_and_invalid_observations():
    assert box([2,2,2])['lower']==2
    for points in ([],[float('nan')],[-1]):
        with pytest.raises(ValueError):box(points)
