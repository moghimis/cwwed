import os
from urllib import parse
from django.conf import settings
from django.core.files.storage import default_storage
from rest_framework import serializers
from named_storms.models import NamedStorm, NamedStormCoveredData, CoveredData, NSEM, CoveredDataProvider


class NamedStormSerializer(serializers.ModelSerializer):

    class Meta:
        model = NamedStorm
        fields = '__all__'


class NamedStormDetailSerializer(NamedStormSerializer):
    covered_data = serializers.SerializerMethodField()

    def get_covered_data(self, storm: NamedStorm):
        return NamedStormCoveredDataSerializer(storm.namedstormcovereddata_set.all(), many=True, context=self.context).data


class CoveredDataSerializer(serializers.ModelSerializer):

    class Meta:
        model = CoveredData
        fields = '__all__'

    providers = serializers.SerializerMethodField()

    def get_providers(self, covered_data: CoveredData):
        return CoveredDataProviderSerializer(covered_data.covereddataprovider_set.all(), many=True).data


class CoveredDataProviderSerializer(serializers.ModelSerializer):

    class Meta:
        model = CoveredDataProvider
        fields = '__all__'


class NamedStormCoveredDataSerializer(serializers.ModelSerializer):

    class Meta:
        model = NamedStormCoveredData
        exclude = ('named_storm',)
        depth = 1


class NSEMSerializer(serializers.ModelSerializer):
    """
    Named Storm Event Model Serializer
    """

    class Meta:
        model = NSEM
        fields = '__all__'

    model_output_upload_path = serializers.SerializerMethodField()
    covered_data_storage_url = serializers.SerializerMethodField()
    thredds_url_nsem = serializers.SerializerMethodField()

    def get_thredds_url_nsem(self, obj: NSEM):
        if not obj.model_output_snapshot_extracted:
            return None
        return '{}://{}'.format(
            self.context['request'].scheme,
            os.path.join(
                self.context['request'].get_host(),
                'thredds',
                'catalog',
                'cwwed',
                parse.quote(obj.named_storm.name),
                parse.quote(settings.CWWED_NSEM_DIR_NAME),
                'v{}'.format(obj.id),
                parse.quote(settings.CWWED_NSEM_PSA_DIR_NAME),
                'catalog.html',
            ))

    def get_covered_data_storage_url(self, obj: NSEM):
        if obj.covered_data_snapshot:
            return default_storage.storage_url(obj.covered_data_snapshot)
        return None

    def validate_model_output_snapshot(self, value):
        """
        Check that it hasn't already been processed
        Check that the path is in the expected format (ie. "NSEM/upload/v68.tgz") and exists in storage
        """
        obj = self.instance  # type: NSEM
        if obj:

            # already extracted
            if obj.model_output_snapshot_extracted:
                raise serializers.ValidationError('Cannot be updated since the model output has already been processed')

            s3_path = self._get_model_output_upload_path(obj)

            # verify the path is in the expected format
            if s3_path != value:
                raise serializers.ValidationError("'model_output_snapshot' should equal '{}'".format(s3_path))

            # remove any prefixed "location" from the default_storage instance
            location_prefix = '{}/'.format(default_storage.location)
            if s3_path.startswith(location_prefix):
                s3_path = s3_path.replace(location_prefix, '')

            # verify the path exists
            if not default_storage.exists(s3_path):
                raise serializers.ValidationError("{} does not exist in storage".format(s3_path))

            return s3_path
        return value

    def get_model_output_upload_path(self, obj: NSEM):
        return self._get_model_output_upload_path(obj)

    @staticmethod
    def _get_model_output_upload_path(obj: NSEM) -> str:
        return default_storage.path(os.path.join(
            settings.CWWED_NSEM_DIR_NAME,
            settings.CWWED_NSEM_UPLOAD_DIR_NAME,
            'v{}.{}'.format(obj.id, settings.CWWED_ARCHIVE_EXTENSION)),
        )
