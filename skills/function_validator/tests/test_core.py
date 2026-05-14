"""
Tests for FunctionValidatorSkill.
"""
import pytest
from ..core import validate_contract
from ..exceptions import InputValidationError, OutputValidationError

def test_validate_contract_success():
    @validate_contract(input_types={'a': int, 'b': str}, output_type=str)
    def sample_func(a, b):
        return f"{b} {a}"
    
    assert sample_func(10, "Count:") == "Count: 10"

def test_validate_contract_input_fail():
    @validate_contract(input_types={'a': int})
    def sample_func(a):
        return a
    
    with pytest.raises(InputValidationError):
        sample_func("not an int")

def test_validate_contract_output_fail():
    @validate_contract(output_type=int)
    def sample_func():
        return "not an int"
    
    with pytest.raises(OutputValidationError):
        sample_func()

def test_validate_contract_no_types():
    @validate_contract()
    def sample_func(x):
        return x
    
    assert sample_func(5) == 5
