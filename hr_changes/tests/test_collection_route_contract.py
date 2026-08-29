from unittest import mock

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from hr_changes.api import identity_changes as identity_api
from hr_changes.api import transfers as transfers_api
from hr_changes.api.urls import urlpatterns


class Hr06CollectionRouteContractTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.callbacks = {str(pattern.pattern): pattern.callback for pattern in urlpatterns}

    def test_transfer_collection_route_reaches_get_and_post_writers(self):
        route = "api/hr/v1/changes/transfers"
        self.assertIs(self.callbacks[route], transfers_api.transfer_collection)
        with mock.patch.object(transfers_api, "transfer_list", return_value=HttpResponse(status=200)) as list_call:
            response = transfers_api.transfer_collection(self.factory.get("/api/hr/v1/changes/transfers"))
        self.assertEqual(response.status_code, 200)
        list_call.assert_called_once()
        with mock.patch.object(transfers_api, "transfer_create", return_value=HttpResponse(status=201)) as create_call:
            response = transfers_api.transfer_collection(self.factory.post("/api/hr/v1/changes/transfers"))
        self.assertEqual(response.status_code, 201)
        create_call.assert_called_once()

    def test_identity_collection_route_reaches_get_and_post_writers(self):
        route = "api/hr/v1/changes/identity-changes"
        self.assertIs(self.callbacks[route], identity_api.identity_change_collection)
        with mock.patch.object(identity_api, "identity_change_list", return_value=HttpResponse(status=200)) as list_call:
            response = identity_api.identity_change_collection(self.factory.get("/api/hr/v1/changes/identity-changes"))
        self.assertEqual(response.status_code, 200)
        list_call.assert_called_once()
        with mock.patch.object(identity_api, "identity_change_create", return_value=HttpResponse(status=201)) as create_call:
            response = identity_api.identity_change_collection(self.factory.post("/api/hr/v1/changes/identity-changes"))
        self.assertEqual(response.status_code, 201)
        create_call.assert_called_once()
