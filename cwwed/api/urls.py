from django.urls import path, include
from rest_framework import routers
from named_storms.api import viewsets as storm_viewsets
from named_storms.api import views
from coastal_act.api import viewsets as coastal_act_viewsets
from rest_framework.authtoken import views as drf_views

router = routers.DefaultRouter()
router.register(r'named-storms', storm_viewsets.NamedStormViewSet)
router.register(r'covered-data', storm_viewsets.CoveredDataViewSet)
router.register(r'nsem', storm_viewsets.NSEMViewset)
router.register(r'coastal-act-projects', coastal_act_viewsets.CoastalActProjectViewSet)
router.register(r'user', coastal_act_viewsets.CurrentUserViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('psa-filter/', views.PSAFilterView.as_view()),
    path('auth/', drf_views.obtain_auth_token),  # authenticates user and returns token
]
