"""
hr_control_center/api/serializers.py

DTO 序列化（后续 S4/S5 列表接口使用）。
"""

from rest_framework import serializers


class MetricContractSerializer(serializers.Serializer):
    metricKey = serializers.CharField()
    value = serializers.IntegerField(allow_null=True)
    status = serializers.CharField()
    asOf = serializers.DateField(allow_null=True)
    period = serializers.DictField(child=serializers.CharField(), required=False)
    scope = serializers.DictField(required=False)
    definitionVersion = serializers.CharField(allow_null=True)
    dataBasis = serializers.CharField(allow_null=True)
    computedAt = serializers.DateTimeField(allow_null=True)
    sourceUpdatedAt = serializers.DateTimeField(allow_null=True)
    maxStaleSeconds = serializers.IntegerField(allow_null=True)
    reasonCode = serializers.CharField(allow_null=True)
    message = serializers.CharField(allow_null=True)
    drilldown = serializers.DictField(required=False)
