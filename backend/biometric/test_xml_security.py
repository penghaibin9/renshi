from unittest.mock import Mock

from django.test import SimpleTestCase

from biometric.cosec import COSECBiometric


class CosecXMLSecurityTests(SimpleTestCase):
    def setUp(self):
        self.device = COSECBiometric(
            machine_ip="192.0.2.10",
            port=80,
            username="device-user",
            password="device-password",
        )

    @staticmethod
    def _response(content):
        return Mock(
            status_code=200,
            headers={"Content-Type": "text/xml"},
            content=content,
        )

    def test_normal_device_xml_is_parsed(self):
        parsed = self.device._COSECBiometric__parse_response(
            self._response(b"<Root><Response-Code>0</Response-Code></Root>")
        )

        self.assertEqual(parsed["Response-Code"], "0")

    def test_entity_expansion_payload_fails_closed(self):
        payload = b"""<?xml version='1.0'?>
        <!DOCTYPE root [<!ENTITY secret SYSTEM 'file:///etc/passwd'>]>
        <Root><Response-Code>&secret;</Response-Code></Root>"""

        parsed = self.device._COSECBiometric__parse_response(
            self._response(payload)
        )

        self.assertEqual(parsed, {"Error": "Invalid XML response"})
