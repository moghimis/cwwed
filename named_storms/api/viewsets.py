from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import DjangoModelPermissionsOrAnonReadOnly
from rest_framework.response import Response

from named_storms.tasks import (
    archive_nsem_covered_data_task, extract_nsem_model_output_task, email_nsem_covered_data_complete_task,
    extract_nsem_covered_data_task,
)
from named_storms.models import NamedStorm, CoveredData, NSEM
from named_storms.api.serializers import NamedStormSerializer, CoveredDataSerializer, NamedStormDetailSerializer, NSEMSerializer


class NamedStormViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = NamedStorm.objects.all()
    serializer_class = NamedStormSerializer
    filter_fields = ('name',)
    search_fields = ('name',)

    def get_serializer_class(self):
        # return a more detailed representation for a specific storm
        if self.action == 'retrieve':
            return NamedStormDetailSerializer
        return super().get_serializer_class()


class CoveredDataViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CoveredData.objects.all()
    serializer_class = CoveredDataSerializer


class NSEMViewset(viewsets.ModelViewSet):
    """
    Named Storm Event Model Viewset
    """
    queryset = NSEM.objects.all()
    serializer_class = NSEMSerializer
    permission_classes = (DjangoModelPermissionsOrAnonReadOnly,)
    filter_fields = ('named_storm__id', 'model_output_snapshot_extracted')

    @action(methods=['get'], detail=False, url_path='per-storm')
    def per_storm(self, request):
        # return the most recent/distinct NSEM records per storm
        return Response(NSEMSerializer(
            self.queryset.filter(model_output_snapshot_extracted=True).order_by('named_storm', '-date_returned').distinct('named_storm'),
            many=True, context=self.get_serializer_context()).data)

    def perform_create(self, serializer):
        # save the instance first so we can create a task to archive the covered data snapshot
        obj = serializer.save()

        # base url for email
        base_url = '{}://{}'.format(
            self.request.scheme,
            self.request.get_host(),
        )

        # create an archive in object storage for the nsem users to download directly
        archive_nsem_covered_data_task.apply_async(
            (obj.id,),
            link=[
                # send an email to the "nsem" user when the archival is complete
                email_nsem_covered_data_complete_task.s(base_url),
                # download and extract archives into file storage so they're available for discovery (i.e opendap)
                extract_nsem_covered_data_task.s()
            ],
        )

    def perform_update(self, serializer):
        # save the instance first so we can create a task to extract the model output snapshot
        obj = serializer.save()
        extract_nsem_model_output_task.delay(obj.id)
