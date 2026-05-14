"""
Tests for AutoFixerSkill.
"""
import pytest
from ..core import auto_fix

def test_auto_fix_string_to_int():
    @auto_fix(input_types={'val': int})
    def add_one(val):
        return val + 1
    
    # "10" (str) -> 10 (int)
    assert add_one("10") == 11

def test_auto_fix_string_to_float():
    @auto_fix(input_types={'val': float})
    def divide_half(val):
        return val / 2
    
    # "5.0" (str) -> 5.0 (float)
    assert divide_half("5.0") == 2.5

def test_auto_fix_string_to_bool():
    @auto_fix(input_types={'flag': bool})
    def check_flag(flag):
        return flag
    
    assert check_flag("true") is True
    assert check_flag("yes") is True
    assert check_flag("1") is True
    assert check_flag("off") is False

def test_auto_fix_no_change_if_valid():
    @auto_fix(input_types={'x': int})
    def multiply(x):
        return x * 2
    
    assert multiply(5) == 10

def test_auto_fix_fallback_on_fail():
    @auto_fix(input_types={'x': int})
    def identity(x):
        return x
    
    # "abc" cannot be int. Should pass "abc" as is and let next layer handle it.
    assert identity("abc") == "abc"
