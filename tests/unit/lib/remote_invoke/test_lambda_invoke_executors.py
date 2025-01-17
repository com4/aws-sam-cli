from unittest import TestCase
from unittest.mock import Mock, patch
from parameterized import parameterized

from samcli.lib.remote_invoke.lambda_invoke_executors import (
    LambdaInvokeExecutor,
    DefaultConvertToJSON,
    LambdaResponseConverter,
    LambdaResponseOutputFormatter,
    InvalidResourceBotoParameterException,
    InvalideBotoResponseException,
    RemoteInvokeOutputFormat,
    ClientError,
    ParamValidationError,
)
from samcli.lib.remote_invoke.remote_invoke_executors import RemoteInvokeExecutionInfo


class TestLambdaInvokeExecutor(TestCase):
    def setUp(self) -> None:
        self.lambda_client = Mock()
        self.function_name = Mock()
        self.lambda_invoke_executor = LambdaInvokeExecutor(self.lambda_client, self.function_name)

    def test_execute_action(self):
        given_payload = Mock()
        given_result = Mock()
        self.lambda_client.invoke.return_value = given_result

        result = self.lambda_invoke_executor._execute_action(given_payload)

        self.assertEqual(result, given_result)
        self.lambda_client.invoke.assert_called_with(
            FunctionName=self.function_name, Payload=given_payload, InvocationType="RequestResponse", LogType="Tail"
        )

    def test_execute_action_invalid_parameter_value_throws_validation_exception(self):
        given_payload = Mock()
        error = ClientError(error_response={"Error": {"Code": "ValidationException"}}, operation_name="invoke")
        self.lambda_client.invoke.side_effect = error
        with self.assertRaises(InvalidResourceBotoParameterException):
            self.lambda_invoke_executor._execute_action(given_payload)

    def test_execute_action_invalid_parameter_key_throws_parameter_validation_exception(self):
        given_payload = Mock()
        error = ParamValidationError(report="Invalid parameters")
        self.lambda_client.invoke.side_effect = error
        with self.assertRaises(InvalidResourceBotoParameterException):
            self.lambda_invoke_executor._execute_action(given_payload)

    def test_execute_action_throws_client_error_exception(self):
        given_payload = Mock()
        error = ClientError(error_response={"Error": {"Code": "MockException"}}, operation_name="invoke")
        self.lambda_client.invoke.side_effect = error
        with self.assertRaises(ClientError):
            self.lambda_invoke_executor._execute_action(given_payload)

    @parameterized.expand(
        [
            ({}, {"InvocationType": "RequestResponse", "LogType": "Tail"}),
            ({"InvocationType": "Event"}, {"InvocationType": "Event", "LogType": "Tail"}),
            (
                {"InvocationType": "DryRun", "Qualifier": "TestQualifier"},
                {"InvocationType": "DryRun", "LogType": "Tail", "Qualifier": "TestQualifier"},
            ),
            (
                {"InvocationType": "RequestResponse", "LogType": "None"},
                {"InvocationType": "RequestResponse", "LogType": "None"},
            ),
            (
                {"FunctionName": "MyFunction", "Payload": "{hello world}"},
                {"InvocationType": "RequestResponse", "LogType": "Tail"},
            ),
        ]
    )
    def test_validate_action_parameters(self, parameters, expected_boto_parameters):
        self.lambda_invoke_executor.validate_action_parameters(parameters)
        self.assertEqual(self.lambda_invoke_executor.request_parameters, expected_boto_parameters)


class TestDefaultConvertToJSON(TestCase):
    def setUp(self) -> None:
        self.lambda_convert_to_default_json = DefaultConvertToJSON()
        self.output_format = RemoteInvokeOutputFormat.DEFAULT

    @parameterized.expand(
        [
            ("Hello World", '"Hello World"'),
            ('{"message": "hello world"}', '{"message": "hello world"}'),
        ]
    )
    def test_conversion(self, given_string, expected_string):
        remote_invoke_execution_info = RemoteInvokeExecutionInfo(given_string, None, {}, self.output_format)
        result = self.lambda_convert_to_default_json.map(remote_invoke_execution_info)
        self.assertEqual(result.payload, expected_string)

    def test_skip_conversion_if_file_provided(self):
        given_payload_path = "foo/bar/event.json"
        remote_invoke_execution_info = RemoteInvokeExecutionInfo(None, given_payload_path, {}, self.output_format)

        self.assertTrue(remote_invoke_execution_info.is_file_provided())
        result = self.lambda_convert_to_default_json.map(remote_invoke_execution_info)

        self.assertIsNone(result.payload)


class TestLambdaResponseConverter(TestCase):
    def setUp(self) -> None:
        self.lambda_response_converter = LambdaResponseConverter()

    def test_lambda_streaming_body_response_conversion(self):
        output_format = RemoteInvokeOutputFormat.DEFAULT
        given_streaming_body = Mock()
        given_decoded_string = "decoded string"
        given_streaming_body.read().decode.return_value = given_decoded_string
        given_test_result = {"Payload": given_streaming_body}
        remote_invoke_execution_info = RemoteInvokeExecutionInfo(None, None, {}, output_format)
        remote_invoke_execution_info.response = given_test_result

        expected_result = {"Payload": given_decoded_string}

        result = self.lambda_response_converter.map(remote_invoke_execution_info)

        self.assertEqual(result.response, expected_result)

    def test_lambda_streaming_body_invalid_response_exception(self):
        output_format = RemoteInvokeOutputFormat.DEFAULT
        given_streaming_body = Mock()
        given_decoded_string = "decoded string"
        given_streaming_body.read().decode.return_value = given_decoded_string
        given_test_result = [given_streaming_body]
        remote_invoke_execution_info = RemoteInvokeExecutionInfo(None, None, {}, output_format)
        remote_invoke_execution_info.response = given_test_result

        with self.assertRaises(InvalideBotoResponseException):
            self.lambda_response_converter.map(remote_invoke_execution_info)


class TestLambdaResponseOutputFormatter(TestCase):
    def setUp(self) -> None:
        self.lambda_response_converter = LambdaResponseOutputFormatter()

    def test_lambda_response_original_boto_output_formatter(self):
        given_response = {"Payload": {"StatusCode": 200, "message": "hello world"}}
        output_format = RemoteInvokeOutputFormat.ORIGINAL_BOTO_RESPONSE

        remote_invoke_execution_info = RemoteInvokeExecutionInfo(None, None, {}, output_format)
        remote_invoke_execution_info.response = given_response
        result = self.lambda_response_converter.map(remote_invoke_execution_info)

        self.assertEqual(result.response, given_response)

    @patch("samcli.lib.remote_invoke.lambda_invoke_executors.base64")
    def test_lambda_response_default_output_formatter(self, base64_mock):
        decoded_log_str = "decoded log string"
        log_str_mock = Mock()
        base64_mock.b64decode().decode.return_value = decoded_log_str
        given_response = {"Payload": {"StatusCode": 200, "message": "hello world"}, "LogResult": log_str_mock}
        output_format = RemoteInvokeOutputFormat.DEFAULT

        remote_invoke_execution_info = RemoteInvokeExecutionInfo(None, None, {}, output_format)
        remote_invoke_execution_info.response = given_response

        expected_result = {"StatusCode": 200, "message": "hello world"}
        result = self.lambda_response_converter.map(remote_invoke_execution_info)

        self.assertEqual(result.response, expected_result)
        self.assertEqual(result.log_output, decoded_log_str)

    @parameterized.expand(
        [
            ({"InvocationType": "DryRun", "Qualifier": "TestQualifier"},),
            ({"InvocationType": "Event", "LogType": None},),
        ]
    )
    def test_non_default_invocation_type_output_formatter(self, parameters):
        given_response = {"StatusCode": 200, "Payload": {"StatusCode": 200, "message": "hello world"}}
        output_format = RemoteInvokeOutputFormat.DEFAULT

        remote_invoke_execution_info = RemoteInvokeExecutionInfo(None, None, parameters, output_format)
        remote_invoke_execution_info.response = given_response

        expected_result = {"StatusCode": 200}
        result = self.lambda_response_converter.map(remote_invoke_execution_info)

        self.assertEqual(result.response, expected_result)
