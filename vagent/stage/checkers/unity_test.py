#coding=utf-8


from typing import Tuple
from vagent.util.functions import get_unity_chip_doc_marks
from vagent.util.functions import import_python_file, dump_as_json
from vagent.tools.testops import RunUnityChipTest
import os

from vagent.stage.checkers.base import Checker


class UnityChipCheckerLabelStructure(Checker):
    def __init__(self, *a, **kw):
        pass

class UnityChipCheckerDutCreation(Checker):
    def __init__(self, *a, **kw):
        pass

class UnityChipCheckerFuncCheck(Checker):
    def __init__(self, *a, **kw):
        pass

class UnityChipCheckerDutFixture(Checker):
    def __init__(self, *a, **kw):
        pass


class UnityChipCheckerFunctionsAndChecks(Checker):
    """
    Checker for Unity chip functions and checks documentation validation.
    
    This class validates functional specification documents to ensure they contain
    adequate coverage of DUT functionality through properly structured function
    groups, functions, and check points following the required documentation format.
    """

    def __init__(self, doc_file, min_functions, min_checks):
        self.doc_file = doc_file
        self.min_functions = min_functions
        self.min_checks = min_checks

    def do_check(self) -> Tuple[bool, str]:
        """
        Perform comprehensive validation of function and check coverage documentation.
        
        Validates:
        1. Document existence and parseability
        2. Proper tag structure (<FG-*>, <FC-*>, <CK-*>)
        3. Minimum coverage requirements
        4. Documentation completeness and consistency
        
        Returns:
            Tuple[bool, str]: Success status and detailed diagnostic message
        """
        # File existence validation
        if not os.path.exists(self.get_path(self.doc_file)):
            return False, f"Documentation file '{self.doc_file}' not found in workspace.\n" +\
                           "Expected location: {}\n".format(self.get_path(self.doc_file)) +\
                           "Action required:\n" +\
                           "1. Create the functional specification document\n" +\
                           "2. Ensure the file path matches the configuration\n" +\
                           "3. Verify workspace structure and file permissions\n" +\
                           "Please refer to Guide_Doc/dut_functions_and_checks.md for format requirements."
        
        # Document parsing and structure validation
        try:
            data = get_unity_chip_doc_marks(self.get_path(self.doc_file))
        except Exception as e:
            error_details = str(e)
            emsg = f"Documentation parsing failed for file '{self.doc_file}': {error_details}\n" + \
                    "Common issues and solutions:\n"
            
            if "\\n" in error_details:
                emsg += "• Literal '\\n' characters detected - use actual line breaks instead of escaped characters\n"
            
            emsg += "• Malformed tags: Ensure proper format <FG-NAME>, <FC-NAME>, <CK-NAME>\n" + \
                    "• Invalid characters: Use only alphanumeric and hyphen in tag names\n" + \
                    "• Missing tag closure: All tags must be properly closed\n" + \
                    "• Encoding issues: Ensure file is saved in UTF-8 format\n" + \
                    "Please review the document format and fix syntax errors.\n" + \
                    "Reference: Guide_Doc/dut_functions_and_checks.md"
            return False, emsg
        
        # Extract coverage information
        check_list = data.get("marks", [])
        count_function = data["count_function"]
        count_check = data["count_checkpoint"]
        
        # Generate detailed diagnostic information
        coverage_summary = self._generate_coverage_summary(data, check_list)
        
        # Validate minimum coverage requirements
        coverage_validation = self._validate_coverage_requirements(count_function, count_check, coverage_summary)
        if not coverage_validation[0]:
            return False, coverage_validation[1]
        
        # Success: All validations passed
        success_msg = "Functional specification validation successful!\n" + \
                      f"✓ Document structure is well-formed and parseable\n" + \
                      f"✓ Coverage requirements met: {count_function} functions (≥{self.min_functions}), " + \
                      f"{count_check} check points (≥{self.min_checks})\n" + \
                      f"✓ Documentation follows proper tagging conventions\n" + \
                      "Your functional specification provides adequate coverage for verification!" + coverage_summary

        return True, success_msg

    def _generate_coverage_summary(self, data, check_list) -> str:
        """
        Generate detailed coverage summary for diagnostic purposes.
        
        Args:
            data: Parsed document data
            check_list: List of all check marks
            
        Returns:
            str: Formatted coverage summary
        """
        coverage_info = "\n\n[COVERAGE_ANALYSIS]:\n"
        coverage_info += f"Function Groups: {data.get('count_group', 0)}\n"
        coverage_info += f"Functions: {data['count_function']}\n"
        coverage_info += f"Check Points: {data['count_checkpoint']}\n"
        
        if check_list:
            coverage_info += "\n[DOCUMENTED_CHECK_POINTS]:\n"
            # Group check points by function group for better organization
            grouped_checks = {}
            for check in check_list:
                parts = check.split('/')
                if len(parts) >= 2:
                    group = parts[0]
                    if group not in grouped_checks:
                        grouped_checks[group] = []
                    grouped_checks[group].append(check)
            
            for group, checks in grouped_checks.items():
                coverage_info += f"\n{group}:\n"
                for check in checks[:5]:  # Limit to first 5 to avoid excessive output
                    coverage_info += f"  • {check}\n"
                if len(checks) > 5:
                    coverage_info += f"  ... and {len(checks) - 5} more\n"
        
        return coverage_info

    def _validate_coverage_requirements(self, count_function, count_check, coverage_summary) -> Tuple[bool, str]:
        """
        Validate that coverage meets minimum requirements.
        
        Args:
            count_function: Number of functions found
            count_check: Number of check points found
            coverage_summary: Coverage analysis summary
            
        Returns:
            Tuple[bool, str]: Validation result and message
        """
        if count_function < self.min_functions:
            return False, f"Insufficient functional coverage: {count_function} functions found, " +\
                           f"minimum required is {self.min_functions}.\n" +\
                           "Action required:\n" +\
                           "1. Analyze DUT functionality more comprehensively\n" +\
                           "2. Add more function groups (<FG-*>) for different operational areas\n" +\
                           "3. Define specific functions (<FC-*>) within each group\n" +\
                           "4. Ensure all major DUT capabilities are covered\n" +\
                           "Each function should represent a distinct testable behavior or operation." + coverage_summary
        
        if count_check < self.min_checks:
            return False, f"Insufficient verification coverage: {count_check} check points found, " +\
                           f"minimum required is {self.min_checks}.\n" +\
                           "Action required:\n" +\
                           "1. Add more check points (<CK-*>) for comprehensive validation\n" +\
                           "2. Include normal operation, boundary conditions, and error scenarios\n" +\
                           "3. Consider different input combinations and edge cases\n" +\
                           "4. Ensure each function has adequate validation points\n" +\
                           "Check points should cover positive, negative, and boundary test cases." + coverage_summary
        
        return True, ""


class UnityChipCheckerDutApi(Checker):
    """
    Checker for Unity chip DUT API implementation validation.

    This class validates DUT API files to ensure they provide adequate
    high-level interface functions for test case implementation, following
    proper naming conventions and architectural patterns.
    """

    def __init__(self, api_file, min_apis, type="api"):
        self.api_file = api_file
        self.min_apis = min_apis

    def do_check(self) -> Tuple[bool, str]:
        """
        Perform comprehensive validation of DUT API implementation.
        
        Validates:
        1. API file existence and accessibility  
        2. Proper API function definitions with 'api_' prefix
        3. Minimum API coverage requirements
        4. Code structure and import statements
        
        Returns:
            Tuple[bool, str]: Success status and detailed diagnostic message
        """
        # File existence validation
        if not os.path.exists(self.get_path(self.api_file)):
            return False, f"DUT API file '{self.api_file}' not found in workspace.\n" +\
                           "Expected location: {}\n".format(self.get_path(self.api_file)) +\
                           "Action required:\n" +\
                           "1. Create the DUT API implementation file\n" +\
                           "2. Implement required API functions with 'api_' prefix\n" +\
                           "3. Include proper imports and DUT fixture setup\n" +\
                           "4. Verify file path matches the test configuration\n" +\
                           "Please refer to Guide_Doc/dut_fixture_and_api.md for implementation guidance."
        
        # Parse and analyze API file
        api_analysis_result = self._analyze_api_file()
        if not api_analysis_result[0]:
            return False, api_analysis_result[1]
        
        api_count, api_list, file_issues = api_analysis_result[1:]
        
        # Generate detailed API information
        api_summary = self._generate_api_summary(api_count, api_list, file_issues)
        
        # Validate minimum API requirements
        if api_count < self.min_apis:
            return False, f"Insufficient DUT API coverage: {api_count} API functions found, " +\
                           f"minimum required is {self.min_apis}.\n" +\
                           "Action required:\n" +\
                           "1. Implement additional 'api_' prefixed functions for key DUT operations\n" +\
                           "2. Cover major functional areas (initialization, operation, cleanup)\n" +\
                           "3. Provide high-level abstractions that hide timing and signal details\n" +\
                           "4. Ensure APIs are reusable across different test scenarios\n" +\
                           "Each API function should encapsulate a meaningful DUT operation." + api_summary
        
        # Success: All validations passed
        success_msg = "DUT API validation successful!\n" + \
                      f"✓ API file is accessible and well-structured\n" + \
                      f"✓ API coverage meets requirements: {api_count} functions (≥{self.min_apis})\n" + \
                      f"✓ All API functions follow proper naming conventions\n" + \
                      "Your DUT API provides adequate abstraction for test implementation!" + api_summary

        return True, success_msg

    def _analyze_api_file(self) -> Tuple[bool, int, list, list]:
        """
        Analyze the API file for structure, functions, and potential issues.
        
        Returns:
            Tuple: (success, api_count, api_list, file_issues)
        """
        api_count = 0
        api_list = []
        file_issues = []
        
        try:
            with open(self.get_path(self.api_file), 'r', encoding='utf-8') as file:
                lines = file.readlines()
        except UnicodeDecodeError:
            return False, "API file encoding error: Unable to read file with UTF-8 encoding.\n" + \
                          "Action required:\n" + \
                          "1. Save the file with UTF-8 encoding\n" + \
                          "2. Remove any non-ASCII characters or properly escape them\n" + \
                          "3. Verify file integrity and format", 0, [], []
        except Exception as e:
            return False, f"API file access error: {str(e)}\n" + \
                          "Please check file permissions and path correctness.", 0, [], []
        
        # Analyze file content
        has_imports = False
        has_fixture = False
        has_create_dut = False
        
        for i, line in enumerate(lines, 1):
            line_stripped = line.strip()
            
            # Check for proper imports
            if line_stripped.startswith("import ") or line_stripped.startswith("from "):
                has_imports = True
            
            # Check for pytest fixture
            if "@pytest.fixture" in line_stripped or "def dut(" in line_stripped:
                has_fixture = True
            
            # Check for DUT creation function
            if line_stripped.startswith("def create_dut("):
                has_create_dut = True
            
            # Look for API functions
            if line_stripped.startswith("def "):
                func_declaration = line_stripped[4:].strip()
                func_name = func_declaration.split('(')[0] if '(' in func_declaration else func_declaration
                
                if func_name.startswith("api_"):
                    api_count += 1
                    # Extract function signature for documentation
                    if '(' in func_declaration:
                        signature = func_declaration[:func_declaration.find(')')+1]
                    else:
                        signature = func_name + "()"
                    api_list.append(f"Line {i}: def {signature}")
        
        # Check for common structural issues
        if not has_imports:
            file_issues.append("Missing import statements - ensure proper module imports")
        if not has_fixture:
            file_issues.append("Missing pytest fixture 'dut' - required for test integration")
        if not has_create_dut:
            file_issues.append("Missing 'create_dut()' function - required for DUT initialization")
        
        return True, api_count, api_list, file_issues

    def _generate_api_summary(self, api_count, api_list, file_issues) -> str:
        """
        Generate detailed API analysis summary.
        
        Args:
            api_count: Number of API functions found
            api_list: List of API function definitions
            file_issues: List of structural issues
            
        Returns:
            str: Formatted API summary
        """
        summary = "\n\n[API_ANALYSIS]:\n"
        summary += f"API Functions Found: {api_count}\n"
        
        if api_list:
            summary += "\n[IMPLEMENTED_APIS]:\n"
            for api_def in api_list:
                summary += f"  • {api_def}\n"
        
        if file_issues:
            summary += "\n[STRUCTURAL_RECOMMENDATIONS]:\n"
            for issue in file_issues:
                summary += f"  ⚠ {issue}\n"
            summary += "\nNote: These are recommendations for best practices, not strict requirements.\n"
        
        return summary

class UnityChipCheckerCoverageCheckpoint(Checker):
    def __init__(self, *a, **k):
        pass


class UnityChipCheckerCoverageGroup(Checker):
    """
    Checker for Unity chip functional coverage groups validation.

    This class validates functional coverage definitions to ensure they properly
    implement coverage groups using the toffee framework, with adequate bins
    and watch points for comprehensive DUT verification coverage.
    """

    def __init__(self, test_path, group_file, min_groups=1):
        self.test_path = test_path
        self.group_file = group_file
        self.min_groups = min_groups

    def do_check(self) -> Tuple[bool, str]:
        """
        Perform comprehensive validation of functional coverage groups.
        
        Validates:
        1. Coverage file existence and importability
        2. Proper get_coverage_groups() function implementation
        3. Valid CovGroup instances with adequate bins
        4. Correct integration with toffee framework
        
        Returns:
            Tuple[bool, str]: Success status and detailed diagnostic message
        """
        # File existence validation
        if not os.path.exists(self.get_path(self.group_file)):
            return False, f"Functional coverage file '{self.group_file}' not found in workspace.\n" +\
                           "Expected location: {}\n".format(self.get_path(self.group_file)) +\
                           "Action required:\n" +\
                           "1. Create the functional coverage definition file\n" +\
                           "2. Implement get_coverage_groups(dut=None) function\n" +\
                           "3. Define coverage groups using toffee.funcov.CovGroup\n" +\
                           "4. Add appropriate watch points and bins\n" +\
                           "Please refer to Guide_Doc/dut_function_coverage_def.md for implementation guidance."
        
        # Module import validation
        module_import_result = self._import_coverage_module()
        if not module_import_result[0]:
            return False, module_import_result[1]
        
        module = module_import_result[1]
        
        # Function existence validation
        get_coverage_groups = getattr(module, "get_coverage_groups", None)
        if get_coverage_groups is None:
            return False, f"Coverage interface error: Function 'get_coverage_groups' not found in '{self.group_file}'.\n" +\
                           "Action required:\n" +\
                           "1. Implement the required function: def get_coverage_groups(dut=None):\n" +\
                           "2. Function should return a list of toffee.funcov.CovGroup instances\n" +\
                           "3. Support dut=None parameter for structure validation\n" +\
                           "4. Ensure function is properly defined at module level\n" +\
                           "This function is the main interface for coverage group access."
        
        # Coverage groups validation
        coverage_validation_result = self._validate_coverage_groups(get_coverage_groups)
        if not coverage_validation_result[0]:
            return False, coverage_validation_result[1]
        
        groups, coverage_summary = coverage_validation_result[1:]
        
        # Success: All validations passed
        success_msg = "Functional coverage validation successful!\n" + \
                      f"✓ Coverage module is properly structured and importable\n" + \
                      f"✓ Coverage requirements met: {len(groups)} groups (≥{self.min_groups})\n" + \
                      f"✓ All coverage groups are valid CovGroup instances with adequate bins\n" + \
                      f"✓ Integration with toffee framework is correct\n" + \
                      "Your functional coverage provides comprehensive verification coverage!" + coverage_summary

        return True, success_msg

    def _import_coverage_module(self) -> Tuple[bool, any]:
        """
        Import and validate the coverage module.
        
        Returns:
            Tuple: (success, module_or_error_message)
        """
        try:
            module = import_python_file(self.get_path(self.group_file),
                                      [self.workspace, self.get_path(self.test_path)])
            return True, module
        except ImportError as e:
            return False, f"Coverage module import failed for '{self.group_file}': {str(e)}\n" + \
                          "Common import issues:\n" + \
                          "1. Missing dependencies - ensure toffee is installed\n" + \
                          "2. Python path issues - verify module location\n" + \
                          "3. Circular import dependencies\n" + \
                          "4. Syntax errors in the coverage file\n" + \
                          "Please fix import errors and ensure all dependencies are available."
        except SyntaxError as e:
            return False, f"Coverage file syntax error in '{self.group_file}': {str(e)}\n" + \
                          "Action required:\n" + \
                          "1. Fix Python syntax errors in the file\n" + \
                          "2. Ensure proper indentation and structure\n" + \
                          "3. Validate function definitions and class usage\n" + \
                          "4. Check for missing imports or typos"
        except Exception as e:
            return False, f"Coverage module loading failed for '{self.group_file}': {str(e)}\n" + \
                          "Possible causes:\n" + \
                          "1. File permission issues\n" + \
                          "2. Invalid file format or encoding\n" + \
                          "3. Runtime errors in module initialization\n" + \
                          "Please review the file structure and fix any issues."

    def _validate_coverage_groups(self, get_coverage_groups) -> Tuple[bool, list, str]:
        """
        Validate the coverage groups implementation.
        
        Args:
            get_coverage_groups: The coverage groups function to validate
            
        Returns:
            Tuple: (success, groups, coverage_summary)
        """
        try:
            # Create a mock DUT for testing - this should work with dut=None
            fake_dut = self
            groups = get_coverage_groups(fake_dut)
            
            # Validate group count
            if len(groups) < self.min_groups:
                return False, f"Insufficient coverage groups: {len(groups)} groups found, " +\
                               f"minimum required is {self.min_groups}.\n" +\
                               "Action required:\n" +\
                               "1. Analyze DUT functionality to identify more coverage areas\n" +\
                               "2. Create additional CovGroup instances for different functional areas\n" +\
                               "3. Ensure each major DUT operation has corresponding coverage\n" +\
                               "4. Consider different operational modes and scenarios\n" +\
                               "Each coverage group should represent a distinct functional area.", [], ""
            
            # Import toffee framework for validation
            try:
                import toffee.funcov as fc
            except ImportError:
                return False, "Toffee framework not available: Cannot validate coverage groups.\n" + \
                              "Action required:\n" + \
                              "1. Install toffee framework: pip install toffee\n" + \
                              "2. Ensure proper environment setup\n" + \
                              "3. Verify framework compatibility\n" + \
                              "Toffee is required for functional coverage implementation.", [], ""
            
            # Validate each coverage group
            group_details = []
            for i, g in enumerate(groups):
                if not isinstance(g, fc.CovGroup):
                    return False, f"Invalid coverage group type: Group {i} in '{self.group_file}' is not a valid 'toffee.funcov.CovGroup' instance.\n" + \
                                   f"Found type: {type(g)}\n" + \
                                   "Action required:\n" + \
                                   "1. Ensure all returned objects are CovGroup instances\n" + \
                                   "2. Use proper toffee.funcov.CovGroup constructor\n" + \
                                   "3. Check import statements and object creation\n" + \
                                   "4. Validate coverage group initialization parameters", [], ""
                
                try:
                    g_data = g.as_dict()
                    bin_count = g_data.get("bin_num_total", 0)
                    
                    if bin_count < 1:
                        return False, f"Empty coverage group: Group '{g.name}' in '{self.group_file}' has no defined bins.\n" + \
                                       "Coverage groups must contain at least one bin (check point).\n" + \
                                       "Action required:\n" + \
                                       "1. Add watch points using Coverage.add_watch_point()\n" + \
                                       "2. Define bins with meaningful check conditions\n" + \
                                       "3. Example: Coverage.add_watch_point(dut, {'CK-NORMAL': lambda x: x.a.value + x.b.value == x.sum.value}, name='FC-ADD')\n" + \
                                       "4. Ensure each functional behavior has corresponding coverage bins", [], ""
                    
                    group_details.append(f"{g.name}: {bin_count} bins")
                    
                except Exception as e:
                    return False, f"Coverage group analysis failed for '{g.name}': {str(e)}\n" + \
                                   "This may indicate issues with coverage group structure or configuration.\n" + \
                                   "Please review the coverage group implementation.", [], ""
            
            # Generate coverage summary
            coverage_summary = self._generate_coverage_summary(groups, group_details)
            
            return True, groups, coverage_summary
            
        except Exception as e:
            return False, f"Coverage groups execution failed: {str(e)}\n" + \
                           "Common issues:\n" + \
                           "1. Runtime errors in coverage group initialization\n" + \
                           "2. Invalid DUT references or parameter issues\n" + \
                           "3. Incorrect toffee framework usage\n" + \
                           "4. Missing or invalid dependencies\n" + \
                           "Please debug the coverage group implementation and fix any runtime issues.", [], ""

    def _generate_coverage_summary(self, groups, group_details) -> str:
        """
        Generate detailed coverage analysis summary.
        
        Args:
            groups: List of coverage groups
            group_details: List of group detail strings
            
        Returns:
            str: Formatted coverage summary
        """
        summary = "\n\n[COVERAGE_ANALYSIS]:\n"
        summary += f"Coverage Groups: {len(groups)}\n"
        
        if group_details:
            summary += "\n[COVERAGE_GROUPS_DETAIL]:\n"
            for detail in group_details:
                summary += f"  • {detail}\n"
        
        total_bins = sum(int(detail.split(': ')[1].split(' bins')[0]) for detail in group_details if ': ' in detail)
        summary += f"\nTotal Coverage Bins: {total_bins}\n"
        
        return summary


class BaseUnityChipCheckerTestCase(Checker):
    """
    Checker for Unity chip test cases.

    This class is used to verify the test cases in Unity chip.
    It checks if the test cases meet the specified minimum requirements.
    """

    def __init__(self, doc_func_check, doc_bug_analysis, test_dir, min_tests=1, timeout=600):
        self.doc_func_check = doc_func_check
        self.doc_bug_analysis = doc_bug_analysis
        self.test_dir = test_dir
        self.min_tests = min_tests
        self.timeout = timeout
        self.run_test = RunUnityChipTest()

    def set_workspace(self, workspace: str):
        """
        Set the workspace for the test case checker.

        :param workspace: The workspace directory to be set.
        """
        super().set_workspace(workspace)
        self.run_test.set_workspace(workspace)
        return self

    def do_check(self, test_case="") -> Tuple[bool, str]:
        """
        Perform the check for test cases.

        Returns:
            report, str_out, str_err: A tuple where the first element is a boolean indicating success or failure,
        """
        if not os.path.exists(self.get_path(self.doc_func_check)):
            return {}, "", f"Function and check documentation file {self.doc_func_check} does not exist in workspace. "+\
                            "Please provide a valid file path. Review your task details."
        self.run_test.set_pre_call_back(
            lambda p: self.set_check_process(p, self.timeout)  # Set the process for the checker
        )
        return self.run_test.do(
            self.test_dir, 
            ex_args=test_case,
            return_stdout=True, return_stderr=True, return_all_checks=True, timeout=self.timeout
        )


class UnityChipCheckerTestTemplate(BaseUnityChipCheckerTestCase):

    def do_check(self) -> Tuple[bool, str]:
        """
        Perform the check for test templates.

        Returns:
            Tuple[bool, str]: A tuple where the first element is a boolean indicating success or failure,
                              and the second element is a message string.
        """
        report, str_out, str_err = super().do_check()
        all_bins_test = report.get("bins_all", [])
        if all_bins_test:
            del report["bins_all"]
        info_report = "\n\n[TEST_REPORT]:\n" + dump_as_json(report)
        info_runtest = info_report + "\n[STDOUT]:\n" + str_out + "\n[STDERR]:\n" + str_err
        if report.get("tests") is None:
            return False, "No test cases found in the report. " +\
                           "Please ensure that the test cases are defined correctly in the workspace." + \
                           "\n" + info_runtest
        if report["tests"]["total"] < self.min_tests:
            return False, f"Insufficient test cases defined: {report['tests']['total']} found, " +\
                           f"minimum required is {self.min_tests}.\n" + \
                           "Please ensure that the test cases are defined in the correct format and location.\n"+ \
                            info_runtest
        try:
            all_bins_docs = get_unity_chip_doc_marks(self.get_path(self.doc_func_check))["marks"]
        except Exception as e:
            return False, f"Failed to parse the function and check documentation file {self.doc_func_check}: {str(e)}\n" + \
                           "Review your task requirements and the file format to fix your documentation file.\n" + info_report
        bins_not_in_docs = []
        bins_not_in_test = []
        for b in all_bins_test:
            if b not in all_bins_docs:
                bins_not_in_docs.append(b)
        for b in all_bins_docs:
            if b not in all_bins_test:
                bins_not_in_test.append(b)
        if len(bins_not_in_docs) > 0:
            return False, f"The flow check points: {', '.join(bins_not_in_docs)} are not defined in the documentation file {self.doc_func_check}.\n" + \
                           "Please ensure that all check points in test case are defined in the documentation file.\n" + \
                           "Review your task requirements and the test cases.\n" + info_runtest
        if len(bins_not_in_test) > 0:
            return False, f"The flow check points: {', '.join(bins_not_in_test)} are defined in the documentation file {self.doc_func_check} but not in the test cases.\n" + \
                           "Please ensure that all check points defined in the documentation are also in the test cases.\n" + \
                           "Review your task requirements and the test cases.\n" + info_runtest

        if report['unmarked_check_points'] > 0:
            unmark_check_points = report['unmarked_check_points_list']
            if len(unmark_check_points) > 0:
                return False, f"Test template validation failed: Found {len(unmark_check_points)} unmarked check points: {', '.join(unmark_check_points)}.\n" + \
                               "In test templates, all check points defined in the documentation must be associated with test cases using 'mark_function'.\n" + \
                               "Please use: dut.fc_cover['FG-GROUP'].mark_function('FC-FUNCTION', test_function_name, ['CK-CHECK1', 'CK-CHECK2'])\n" + \
                               "This ensures proper coverage mapping between documentation and test implementation.\n" + \
                               "Review your task requirements and complete the check point markings.\n" + info_runtest

        if report['test_function_with_no_check_point_mark'] > 0:
            unmarked_functions = report['test_function_with_no_check_point_mark_list']
            return False, f"Test template validation failed: Found {report['test_function_with_no_check_point_mark']} test functions without check point marks: {', '.join(unmarked_functions)}.\n" + \
                           "In test templates, every test function must be associated with specific check points through 'mark_function' calls.\n" + \
                           "Each test function should:\n" + \
                           "1. Include coverage marking at the beginning: dut.fc_cover['FG-GROUP'].mark_function('FC-FUNCTION', function_name, ['CK-POINTS'])\n" + \
                           "2. Have clear TODO comments explaining what needs to be implemented\n" + \
                           "3. End with 'assert False, \"Not implemented\"' to prevent accidental passing\n" + \
                           "Please add proper function markings according to the test template specification.\n" + info_runtest

        # Additional template-specific validations
        template_validation_result = self._validate_template_structure(report, str_out, str_err)
        if not template_validation_result[0]:
            return False, template_validation_result[1] + info_runtest

        # Success message with template-specific details
        success_msg = "Test template validation successful!\n" + \
                      f"✓ Generated {report['tests']['total']} test case templates (all properly failing as expected)\n" + \
                      f"✓ All {len(all_bins_test)} check points are properly documented and marked in test functions\n" + \
                      f"✓ Coverage mapping is consistent between documentation and test implementation\n" + \
                      f"✓ Template structure follows the required format with proper TODO comments and fail assertions\n" + \
                      "Your test templates are ready for implementation! Each test function provides clear guidance for the actual test logic to be implemented." + info_report

        return True, success_msg

    def _validate_template_structure(self, report, str_out, str_err) -> Tuple[bool, str]:
        """
        Validate the structure and requirements specific to test templates.
        
        Args:
            report: Test execution report
            str_out: Standard output from test execution
            str_err: Standard error from test execution
            
        Returns:
            Tuple[bool, str]: Validation result and message
        """
        # Check that all tests failed as expected in template
        if report.get("tests", {}).get("fails", 0) != report.get("tests", {}).get("total", 0):
            return False, "Test template structure validation failed: Not all test functions are properly failing.\n" + \
                          "In test templates, ALL test functions must fail with 'assert False, \"Not implemented\"' to indicate they are templates.\n" + \
                          "This prevents incomplete templates from being accidentally considered as passing tests.\n" + \
                          "Please ensure every test function ends with the required fail assertion."
        
        # Check for proper TODO comments (this would require parsing the actual test files)
        # For now, we rely on the fact that properly structured templates should fail with "Not implemented"
        if "Not implemented" not in str_out and "Not implemented" not in str_err:
            return False, "Test template structure validation failed: Template functions should contain 'Not implemented' messages.\n" + \
                          "Test templates must include 'assert False, \"Not implemented\"' statements to clearly indicate unfinished implementation.\n" + \
                          "This helps distinguish between actual test failures and template placeholders."
        
        return True, "Template structure validation passed."



class UnityChipCheckerTestCase(BaseUnityChipCheckerTestCase):

    def do_check(self, test_case="") -> Tuple[bool, str]:
        """
        Perform comprehensive check for implemented test cases.
        
        This checker validates:
        1. Test execution results and coverage
        2. Consistency between documentation and test implementation
        3. Proper handling of failed check points through bug analysis
        4. Complete coverage mapping between tests and documentation
        
        Args:
            test_case: Optional specific test case to run
            
        Returns:
            Tuple[bool, str]: Success status and detailed message
        """
        # Execute tests and get comprehensive report
        report, str_out, str_err = super().do_check(test_case)
        all_bins_test = report.get("bins_all", [])
        if all_bins_test:
            del report["bins_all"]
        
        # Prepare diagnostic information
        info_report = "\n\n[TEST_EXECUTION_REPORT]:\n" + dump_as_json(report)
        info_runtest = info_report + "\n[STDOUT]:\n" + str_out + "\n[STDERR]:\n" + str_err
        
        # Basic validation: Check if tests exist
        if report.get("tests") is None:
            return False, "Test execution failed: No test cases found in the report.\n" +\
                           "Possible causes:\n" +\
                           "1. Test files are not properly named (should start with 'test_')\n" +\
                           "2. Test functions are not properly defined (should start with 'test_' and take 'dut' parameter)\n" +\
                           "3. Import errors in test files\n" +\
                           "Please ensure test cases are defined correctly in the workspace." + \
                           "\n" + info_runtest
        
        # Validate minimum test count requirement
        if report["tests"]["total"] < self.min_tests:
            return False, f"Insufficient test coverage: {report['tests']['total']} test cases found, " +\
                           f"minimum required is {self.min_tests}.\n" + \
                           "Please ensure that:\n" + \
                           "1. All required test scenarios are implemented\n" + \
                           "2. Test functions follow naming conventions (test_*)\n" + \
                           "3. Each functional area has adequate test coverage\n" + \
                           info_runtest
        
        # Parse documentation marks for validation
        try:
            all_bins_docs = get_unity_chip_doc_marks(self.get_path(self.doc_func_check))["marks"]
        except Exception as e:
            return False, f"Documentation parsing failed for file '{self.doc_func_check}': {str(e)}\n" + \
                           "Common issues:\n" + \
                           "1. Malformed tags (ensure proper <FG-*>, <FC-*>, <CK-*> format)\n" + \
                           "2. Encoding issues or special characters\n" + \
                           "3. Invalid document structure\n" + \
                           "Please review your documentation format and fix any syntax errors.\n" + info_report
        
        # Cross-validation: Check consistency between documentation and test implementation
        bins_not_in_docs = []
        bins_not_in_test = []
        
        for b in all_bins_test:
            if b not in all_bins_docs:
                bins_not_in_docs.append(b)
        
        for b in all_bins_docs:
            if b not in all_bins_test:
                bins_not_in_test.append(b)
        
        if len(bins_not_in_docs) > 0:
            return False, f"Documentation inconsistency: Test implementation contains undocumented check points: {', '.join(bins_not_in_docs)}\n" + \
                           "These check points are used in tests but not defined in documentation file '{}'.\n".format(self.doc_func_check) + \
                           "Action required:\n" + \
                           "1. Add missing check points to the documentation with proper <CK-*> tags\n" + \
                           "2. Or remove unused check points from test implementation\n" + \
                           "3. Ensure consistency between test logic and functional requirements\n" + \
                           info_runtest
        
        if len(bins_not_in_test) > 0:
            return False, f"Test coverage gap: Documentation defines check points not implemented in tests: {', '.join(bins_not_in_test)}\n" + \
                           "These check points are documented but missing from test implementation.\n" + \
                           "Action required:\n" + \
                           "1. Implement test cases that cover these check points\n" + \
                           "2. Use proper mark_function() calls to associate tests with check points\n" + \
                           "3. Ensure complete functional coverage as specified in documentation\n" + \
                           info_runtest
        
        # Advanced analysis: Handle failed check points and bug analysis
        failed_check = report.get('faild_check_point_list', [])
        failed_check_passed_funcs = report.get('faild_check_point_passed_funcs', {})
        fails_with_no_mark = []
        fails_with_passed_funcs = []
        marked_checks = []
        
        # Process failed check points if any exist
        if failed_check:
            bug_analysis_result = self._process_bug_analysis(failed_check, failed_check_passed_funcs)
            if not bug_analysis_result[0]:
                return False, bug_analysis_result[1] + info_runtest
            marked_checks = bug_analysis_result[2]
            fails_with_no_mark = bug_analysis_result[3]
            fails_with_passed_funcs = bug_analysis_result[4]
        
        # Validate failed check points handling
        if len(fails_with_no_mark) > 0:
            return False, f"Unanalyzed test failures detected: {', '.join(fails_with_no_mark)}\n" + \
                           "Test failures must be properly analyzed and documented. Options:\n" + \
                           "1. If these are actual DUT bugs, document them in '{}' with confidence ratings\n".format(self.doc_bug_analysis) + \
                           "2. If these are test issues, fix the test logic to make them pass\n" + \
                           "3. Review test implementation and DUT behavior to determine root cause\n" + \
                           info_runtest
        
        if len(fails_with_passed_funcs) > 0:
            fails_with_passed_funcs_str = []
            for f in fails_with_passed_funcs:
                fails_with_passed_funcs_str.append(f"{f[0]} (passed funcs: {', '.join(f[1])})")
            return False, f"Inconsistent test behavior: Check points failed but associated functions passed: {', '.join(fails_with_passed_funcs_str)}\n" + \
                           "This indicates a logic error in test implementation:\n" + \
                           "1. When a check point fails, all related test functions should also fail\n" + \
                           "2. Review the mark_function() associations to ensure correctness\n" + \
                           "3. Check test assertions and validation logic\n" + \
                           info_runtest
        
        # Final coverage validation: Ensure all check points are properly marked
        coverage_validation_result = self._validate_coverage_completeness(report, marked_checks)
        if not coverage_validation_result[0]:
            return False, coverage_validation_result[1] + info_runtest

        # Success: All validations passed
        success_msg = "Test case validation successful!\n" + \
                      f"✓ Executed {report['tests']['total']} test cases with comprehensive coverage\n" + \
                      f"✓ All {len(all_bins_test)} check points are properly implemented and documented\n" + \
                      f"✓ Test-documentation consistency verified\n"
        
        if failed_check:
            success_msg += f"✓ {len(failed_check)} failed check points properly analyzed and documented as potential DUT bugs\n"
        else:
            success_msg += "✓ All check points passed - no issues detected in DUT behavior\n"
        
        success_msg += "✓ Coverage mapping between tests and documentation is complete\n" + \
                       "Your test implementation successfully validates the DUT functionality!" + info_report

        return True, success_msg

    def _process_bug_analysis(self, failed_check, failed_check_passed_funcs):
        """
        Process and validate bug analysis documentation for failed check points.
        
        Args:
            failed_check: List of failed check points
            failed_check_passed_funcs: Dictionary of failed check points with passed functions
            
        Returns:
            Tuple: (success, message, marked_checks, fails_with_no_mark, fails_with_passed_funcs)
        """
        marked_checks = []
        fails_with_no_mark = []
        fails_with_passed_funcs = []
        
        if os.path.exists(self.get_path(self.doc_bug_analysis)):
            try:
                marked_bugs = get_unity_chip_doc_marks(self.get_path(self.doc_bug_analysis))
            except Exception as e:
                return False, f"Bug analysis documentation parsing failed for file '{self.doc_bug_analysis}': {str(e)}\n" + \
                               "Common issues:\n" + \
                               "1. Malformed bug analysis tags\n" + \
                               "2. Invalid confidence rating format\n" + \
                               "3. Encoding or syntax errors\n" + \
                               "Please review and fix the bug analysis documentation format.", [], [], []
            
            # Validate bug analysis marks format
            for c in marked_bugs["marks"]:
                labels = c.split("/")
                if not labels[-1].startswith("BUG-RATE-"):
                    return False, f"Invalid bug analysis format in '{self.doc_bug_analysis}': mark '{c}' missing 'BUG-RATE-' prefix.\n" + \
                                   "Correct format: <FG-GROUP>/<FC-FUNCTION>/<CK-CHECK>/<BUG-RATE-XX>\n" + \
                                   "Example: <BUG-RATE-80> indicates 80% confidence that this is a DUT bug.\n" + \
                                   "Please ensure all bug analysis marks follow this format.", [], [], []
                
                try:
                    confidence = int(labels[-1].split("BUG-RATE-")[1])
                    if not (0 <= confidence <= 100):
                        raise ValueError("Confidence must be 0-100")
                except (IndexError, ValueError):
                    return False, f"Invalid confidence rating in '{self.doc_bug_analysis}': '{labels[-1]}'\n" + \
                                   "Confidence ratings must be integers between 0-100.\n" + \
                                   "Example: <BUG-RATE-75> for 75% confidence.", [], [], []
                
                marked_checks.append("/".join(labels[:-1]))
            
            # Categorize failed check points
            for fail_check in failed_check:
                if fail_check not in marked_checks:
                    fails_with_no_mark.append(fail_check)
                if fail_check in failed_check_passed_funcs:
                    fails_with_passed_funcs.append([fail_check, failed_check_passed_funcs[fail_check]])
        else:
            # No bug analysis file - all failures are unanalyzed
            fails_with_no_mark = failed_check
        
        return True, "", marked_checks, fails_with_no_mark, fails_with_passed_funcs

    def _validate_coverage_completeness(self, report, marked_checks):
        """
        Validate that all check points and test functions are properly associated.
        
        Args:
            report: Test execution report
            marked_checks: List of check points marked in bug analysis
            
        Returns:
            Tuple[bool, str]: Validation result and message
        """
        if report['unmarked_check_points'] > 0:
            unmark_check_points = []
            for m in report['unmarked_check_points_list']:
                if m not in marked_checks:
                    unmark_check_points.append(m)
            
            if len(unmark_check_points) > 0:
                return False, f"Coverage mapping incomplete: {len(unmark_check_points)} check points not associated with test functions: {', '.join(unmark_check_points)}\n" + \
                               "Action required:\n" + \
                               "1. Use mark_function() calls to associate these check points with appropriate test functions\n" + \
                               "2. Ensure every check point defined in documentation has corresponding test coverage\n" + \
                               "3. Review test function organization and coverage mapping\n"
        
        if report['test_function_with_no_check_point_mark'] > 0:
            unmarked_functions = report['test_function_with_no_check_point_mark_list']
            return False, f"Test function mapping incomplete: {report['test_function_with_no_check_point_mark']} test functions not associated with check points: {', '.join(unmarked_functions)}\n" + \
                           "Action required:\n" + \
                           "1. Add mark_function() calls to associate these functions with appropriate check points\n" + \
                           "2. Ensure every test function validates specific documented functionality\n" + \
                           "3. Review test organization and ensure complete traceability\n"
        
        return True, ""
