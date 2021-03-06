# Copyright 2017 99cloud, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import importlib
import json
import os
import tempfile
from unittest import mock

import ddt
import requests
import yaml

from tacker.common import exceptions
from tacker import context
from tacker.extensions import vnfm
from tacker import objects
from tacker.tests.common import helpers
from tacker.tests import constants
from tacker.tests.unit import base
from tacker.tests.unit.db import utils
from tacker.tests.unit.vnfm.infra_drivers.openstack.fixture_data import client
from tacker.tests.unit.vnfm.infra_drivers.openstack.fixture_data import \
    fixture_data_utils as fd_utils
from tacker.tests import uuidsentinel
from tacker.vnfm.infra_drivers.openstack import openstack


@ddt.ddt
class TestOpenStack(base.FixturedTestCase):
    client_fixture_class = client.ClientFixture
    sdk_connection_fixure_class = client.SdkConnectionFixture

    def setUp(self):
        super(TestOpenStack, self).setUp()
        self.openstack = openstack.OpenStack()
        self.context = context.get_admin_context()
        self.heat_url = client.HEAT_URL
        self.glance_url = client.GLANCE_URL
        self.instance_uuid = uuidsentinel.instance_id
        self.stack_id = uuidsentinel.stack_id
        self.auth_attr = None
        self.plugin = None
        self.json_headers = {'content-type': 'application/json',
                             'location': 'http://heat-api/stacks/'
                             + self.instance_uuid + '/myStack/60f83b5e'}
        self._mock('tacker.common.clients.OpenstackClients.heat', self.cs)
        mock.patch('tacker.common.clients.OpenstackSdkConnection.'
                   'openstack_connection', return_value=self.sdk_conn).start()
        self.mock_log = mock.patch('tacker.vnfm.infra_drivers.openstack.'
                                   'openstack.LOG').start()
        mock.patch('time.sleep', return_value=None).start()

    def _response_in_wait_until_stack_ready(self, status_list,
                                            stack_outputs=True):
        # response for heat_client's get()
        for status in status_list:
            url = self.heat_url + '/stacks/' + self.instance_uuid
            json = {'stack': fd_utils.get_dummy_stack(stack_outputs,
                                                      status=status)}
            self.requests_mock.register_uri('GET', url, json=json,
                                            headers=self.json_headers)

    def _response_in_resource_get(self, id, res_name=None):
        # response for heat_client's resource_get()
        if res_name:
            url = self.heat_url + '/stacks/' + id + ('/myStack/60f83b5e/'
                                                'resources/') + res_name
        else:
            url = self.heat_url + '/stacks/' + id

        json = {'resource': fd_utils.get_dummy_resource()}
        self.requests_mock.register_uri('GET', url, json=json,
                                        headers=self.json_headers)

    def _response_in_stack_get(self, id, stack_status='CREATE_COMPLETE'):
        # response for heat_client's stack_get()
        url = self.heat_url + '/stacks/' + id

        json = {'stack': fd_utils.get_dummy_stack(status=stack_status)}
        self.requests_mock.register_uri('GET', url, json=json,
                                        headers=self.json_headers)

    def _response_in_stack_update(self, id):
        # response for heat_client's stack_patch()
        url = self.heat_url + '/stacks/' + id

        self.requests_mock.register_uri('PATCH', url,
                                        headers=self.json_headers)

    def _response_resource_mark_unhealthy(self, id, resources,
            raise_exception=False):
        # response for heat_client's heatclient.resource_mark_unhealthy
        if not resources:
            return

        class MyException(Exception):
            pass

        for resource in resources:
            url = os.path.join(self.heat_url, 'stacks', id,
                    'myStack/60f83b5e/resources', resource['resource_name'])
            if raise_exception:
                self.requests_mock.register_uri('PATCH', url,
                    exc=MyException("Any stuff"))
            else:
                self.requests_mock.register_uri('PATCH', url)

    def _json_load(self, input_file):
        json_file = os.path.abspath(os.path.join(os.path.dirname(__file__),
                    "../../../../etc/samples/lcm_instantiate_request/",
                    str(input_file)))
        with open(json_file) as f:
            json_dict = json.load(f)
        return json_dict

    def _read_file(self):
        yaml_file = os.path.abspath(os.path.join(os.path.dirname(__file__),
                    "../../../../etc/samples/",
                    "hot_lcm_user_data.yaml"))
        with open(yaml_file, 'r') as f:
            yaml_file_dict = yaml.safe_load(f)
        return yaml_file_dict

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_normal(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_normal"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = None
        vnf_resource = type('', (), {})
        vnf_resource.resource_identifier = constants.INVALID_UUID
        grant_info_test = {'vdu_name': {vnf_resource}}
        self.openstack.create(self.plugin, self.context, vnf,
                self.auth_attr, inst_req_info=inst_req_info_test,
                vnf_package_path=vnf_package_path_test,
                base_hot_dict=base_hot_dict_test,
                grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_heat_stack(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict = None
        vnf_package_path = None
        self.openstack.create(self.plugin, self.context, vnf,
                self.auth_attr, base_hot_dict, vnf_package_path)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_userdata_none(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_normal"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        # delete lcm-operation-user-data from additionalParams
        del test_json['additionalParams']['lcm-operation-user-data']

        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = None
        grant_info_test = None
        self.assertRaises(vnfm.LCMUserDataFailed,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, base_hot_dict_test,
                          vnf_package_path_test,
                          inst_req_info=inst_req_info_test,
                          grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_userdataclass_none(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_normal"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        # delete lcm-operation-user-data-class from additionalParams
        del test_json['additionalParams']['lcm-operation-user-data-class']

        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = None
        grant_info_test = None
        self.assertRaises(vnfm.LCMUserDataFailed,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, base_hot_dict_test,
                          vnf_package_path_test,
                          inst_req_info=inst_req_info_test,
                          grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_userdata_null(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_normal"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        # set null to setlcm-operation-user-data from additionalParams
        test_json['additionalParams']['lcm-operation-user-data'] = ''

        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = None
        grant_info_test = None
        self.assertRaises(vnfm.LCMUserDataFailed,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, base_hot_dict_test,
                          vnf_package_path_test,
                          inst_req_info=inst_req_info_test,
                          grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_userdataclass_null(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_normal"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        # set null to setlcm-operation-user-data-class from additionalParams
        test_json['additionalParams']['lcm-operation-user-data-class'] = ''

        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = None
        grant_info_test = None
        self.assertRaises(vnfm.LCMUserDataFailed,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, base_hot_dict_test,
                          vnf_package_path_test,
                          inst_req_info=inst_req_info_test,
                          grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_import_module_exception(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_normal"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = None
        grant_info_test = None
        with mock.patch.object(importlib, 'import_module') as mock_importlib:
            mock_importlib.side_effect = Exception('Test Exception')
            self.assertRaises(vnfm.LCMUserDataFailed,
                              self.openstack.create,
                              self.plugin, self.context, vnf,
                              self.auth_attr, base_hot_dict_test,
                              vnf_package_path_test,
                              inst_req_info=inst_req_info_test,
                              grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_getattr_none(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_normal"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = None
        grant_info_test = None
        with mock.patch.object(importlib, 'import_module') as mock_importlib:
            mock_importlib.return_value = None
            self.assertRaises(vnfm.LCMUserDataFailed,
                              self.openstack.create,
                              self.plugin, self.context, vnf,
                              self.auth_attr, base_hot_dict_test,
                              vnf_package_path_test,
                              inst_req_info=inst_req_info_test,
                              grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_missing_file(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_userdata_none"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = None
        vnf_resource = type('', (), {})
        vnf_resource.resource_identifier = constants.INVALID_UUID
        grant_info_test = {'vdu_name': {vnf_resource}}
        self.assertRaises(vnfm.LCMUserDataFailed,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, inst_req_info=inst_req_info_test,
                          vnf_package_path=vnf_package_path_test,
                          base_hot_dict=base_hot_dict_test,
                          grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_return_none_dict(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_userdata_non_dict"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        test_json['additionalParams']['lcm-operation-user-data'] = \
            'UserData/lcm_user_data_non_dict.py'
        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = None
        vnf_resource = type('', (), {})
        vnf_resource.resource_identifier = constants.INVALID_UUID
        grant_info_test = {'vdu_name': {vnf_resource}}
        self.assertRaises(vnfm.LCMUserDataFailed,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, inst_req_info=inst_req_info_test,
                          vnf_package_path=vnf_package_path_test,
                          base_hot_dict=base_hot_dict_test,
                          grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_none_base_hot_dict(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        inst_req_info_test.additional_params = test_json['additionalParams']
        base_hot_dict_test = None
        vnf_package_path_test = None
        grant_info_test = None
        self.assertRaises(vnfm.LCMUserDataFailed,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, base_hot_dict_test,
                          vnf_package_path_test,
                          inst_req_info=inst_req_info_test,
                          grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_invalid_user_data(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_userdata_normal"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        # set dummy to setlcm-operation-user-data-class from additionalParams
        test_json['additionalParams']['lcm-operation-user-data-class'] = \
            'DummyUserData'

        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = None
        grant_info_test = None
        self.assertRaises(vnfm.LCMUserDataFailed,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, base_hot_dict_test,
                          vnf_package_path_test,
                          inst_req_info=inst_req_info_test,
                          grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_invalid_user_data_class(self,
            mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_userdata_normal"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        # set dummy to setlcm-operation-user-data-class from additionalParams
        test_json['additionalParams']['lcm-operation-user-data-class'] = \
            'DummyUserData'

        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = None
        grant_info_test = None
        self.assertRaises(vnfm.LCMUserDataFailed,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, base_hot_dict_test,
                          vnf_package_path_test,
                          inst_req_info=inst_req_info_test,
                          grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_lcm_user_data_and_user_data_class_no_value(self,
            mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_userdata_normal"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        # set null to setlcm-operation-user-data and
        # lcm-operation-user-data-class from additionalParams
        test_json['additionalParams']['lcm-operation-user-data'] = ''
        test_json['additionalParams']['lcm-operation-user-data-class'] = ''

        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = test_json['extVirtualLinks']
        vnf_resource = type('', (), {})
        vnf_resource.resource_identifier = constants.INVALID_UUID
        grant_info_test = {'vdu_name': {vnf_resource}}
        self.assertRaises(vnfm.LCMUserDataFailed,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, inst_req_info=inst_req_info_test,
                          vnf_package_path=vnf_package_path_test,
                          base_hot_dict=base_hot_dict_test,
                          grant_info=grant_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_lcm_user_data_and_user_data_class_none(self,
            mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_userdata_normal"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        # delete lcm-operation-user-data and
        # lcm-operation-user-data-class from additionalParams
        del test_json['additionalParams']['lcm-operation-user-data']
        del test_json['additionalParams']['lcm-operation-user-data-class']

        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = test_json['extVirtualLinks']
        base_hot_dict = None
        self.assertRaises(BaseException,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, base_hot_dict,
                          vnf_package_path=vnf_package_path_test,
                          inst_req_info=inst_req_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_no_additionalparams(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_userdata_normal"))
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        inst_req_info_test = type('', (), {})
        inst_req_info_test.additional_params = None
        inst_req_info_test.ext_virtual_links = None
        base_hot_dict = None
        self.assertRaises(BaseException,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, base_hot_dict,
                          vnf_package_path=vnf_package_path_test,
                          inst_req_info=inst_req_info_test)

    @mock.patch('tacker.common.clients.OpenstackClients')
    def test_create_instance_exception(self, mock_OpenstackClients_heat):
        vnf = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        vnf['placement_attr'] = {'region_name': 'dummy_region'}
        base_hot_dict_test = self._read_file()
        vnf_package_path_test = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
                         "../../../../etc/samples/etsi/nfv",
                         "user_data_sample_userdata_invalid_script"))
        inst_req_info_test = type('', (), {})
        test_json = self._json_load(
            'instantiate_vnf_request_lcm_userdata.json')
        test_json['additionalParams']['lcm-operation-user-data'] = \
            'UserData/lcm_user_data_invalid_script.py'
        inst_req_info_test.additional_params = test_json['additionalParams']
        inst_req_info_test.ext_virtual_links = None
        vnf_resource = type('', (), {})
        vnf_resource.resource_identifier = constants.INVALID_UUID
        grant_info_test = {'vdu_name': {vnf_resource}}
        self.assertRaises(vnfm.LCMUserDataFailed,
                          self.openstack.create,
                          self.plugin, self.context, vnf,
                          self.auth_attr, inst_req_info=inst_req_info_test,
                          vnf_package_path=vnf_package_path_test,
                          base_hot_dict=base_hot_dict_test,
                          grant_info=grant_info_test)

    def test_create_wait(self):
        self._response_in_wait_until_stack_ready(["CREATE_IN_PROGRESS",
                                                 "CREATE_COMPLETE"])
        vnf_dict = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        self.openstack.create_wait(None, None,
                                   vnf_dict, self.instance_uuid, None)
        self.mock_log.debug.assert_called_with('outputs %s',
                                         fd_utils.get_dummy_stack()['outputs'])
        self.assertEqual(helpers.compact_byte('{"VDU1": "192.168.120.216"}'),
                         vnf_dict['mgmt_ip_address'])

    def test_create_wait_without_mgmt_ips(self):
        self._response_in_wait_until_stack_ready(["CREATE_IN_PROGRESS",
                                                 "CREATE_COMPLETE"],
                                                 stack_outputs=False)
        vnf_dict = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        self.openstack.create_wait(None, None,
                                   vnf_dict, self.instance_uuid, None)
        self.mock_log.debug.assert_called_with('outputs %s',
                          fd_utils.get_dummy_stack(outputs=False)['outputs'])
        self.assertIsNone(vnf_dict['mgmt_ip_address'])

    def test_create_wait_with_scaling_group_names(self):
        self._response_in_wait_until_stack_ready(["CREATE_IN_PROGRESS",
                                                 "CREATE_COMPLETE"])
        self._response_in_resource_get(self.instance_uuid,
                                       res_name='SP1_group')
        url = self.heat_url + '/stacks/' + self.stack_id + '/resources'
        json = {'resources': [fd_utils.get_dummy_resource()]}
        self.requests_mock.register_uri('GET', url, json=json,
                                        headers=self.json_headers)
        self._response_in_resource_get(self.stack_id)
        vnf_dict = utils.get_dummy_vnf(scaling_group=True)
        self.openstack.create_wait(None, None, vnf_dict, self.instance_uuid,
                                   None)
        self.assertEqual(helpers.compact_byte('{"vdu1": ["test1"]}'),
                         vnf_dict['mgmt_ip_address'])

    def test_create_wait_failed_with_stack_retries_0(self):
        self._response_in_wait_until_stack_ready(["CREATE_IN_PROGRESS"])
        vnf_dict = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        self.assertRaises(vnfm.VNFCreateWaitFailed,
                          self.openstack.create_wait,
                          None, None, vnf_dict, self.instance_uuid, None)

    def test_create_wait_failed_with_stack_retries_not_0(self):
        self._response_in_wait_until_stack_ready(["CREATE_IN_PROGRESS",
                                                 "FAILED"])
        vnf_dict = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        self.assertRaises(vnfm.VNFCreateWaitFailed,
                          self.openstack.create_wait,
                          None, None, vnf_dict, self.instance_uuid, {})

    def _exception_response(self):
        url = self.heat_url + '/stacks/' + self.instance_uuid
        body = {"error": Exception("any stuff")}
        self.requests_mock.register_uri('GET', url, body=body,
                    status_code=404, headers=self.json_headers)

    def test_create_wait_with_exception(self):
        self._exception_response()
        vnf_dict = utils.get_dummy_vnf(instance_id=self.instance_uuid)
        self.assertRaises(vnfm.VNFCreateWaitFailed,
                          self.openstack.create_wait,
                          None, None, vnf_dict, self.instance_uuid, None)

    def test_delete_wait_failed_with_stack_retries_0(self):
        self._response_in_wait_until_stack_ready(["DELETE_IN_PROGRESS"])
        self.assertRaises(vnfm.VNFDeleteWaitFailed,
                          self.openstack.delete_wait,
                          None, None, self.instance_uuid, None, None)

    def test_delete_wait_stack_retries_not_0(self):
        self._response_in_wait_until_stack_ready(["DELETE_IN_PROGRESS",
                                                 "FAILED"])
        self.assertRaises(vnfm.VNFDeleteWaitFailed,
                          self.openstack.delete_wait,
                          None, None, self.instance_uuid, None, None)
        self.mock_log.warning.assert_called_once()

    def test_update_wait(self):
        self._response_in_wait_until_stack_ready(["CREATE_COMPLETE"])
        vnf_dict = utils.get_dummy_vnf(status='PENDING_UPDATE',
                                       instance_id=self.instance_uuid)
        self.openstack.update_wait(None, None, vnf_dict, None)
        self.mock_log.debug.assert_called_with('outputs %s',
                                    fd_utils.get_dummy_stack()['outputs'])
        self.assertEqual(helpers.compact_byte('{"VDU1": "192.168.120.216"}'),
                         vnf_dict['mgmt_ip_address'])

    def test_heal_wait(self):
        self._response_in_wait_until_stack_ready(["UPDATE_IN_PROGRESS",
                                                 "UPDATE_COMPLETE"])
        vnf_dict = utils.get_dummy_vnf(status='PENDING_HEAL',
                                       instance_id=self.instance_uuid)
        self.openstack.heal_wait(None, None, vnf_dict, None)
        self.mock_log.debug.assert_called_with('outputs %s',
                                    fd_utils.get_dummy_stack()['outputs'])
        self.assertEqual(helpers.compact_byte('{"VDU1": "192.168.120.216"}'),
                         vnf_dict['mgmt_ip_address'])

    def test_heal_wait_without_mgmt_ips(self):
        self._response_in_wait_until_stack_ready(["UPDATE_IN_PROGRESS",
                                                 "UPDATE_COMPLETE"],
                                                 stack_outputs=False)
        vnf_dict = utils.get_dummy_vnf(status='PENDING_HEAL',
                                       instance_id=self.instance_uuid)
        self.openstack.heal_wait(None, None, vnf_dict, None)
        self.mock_log.debug.assert_called_with('outputs %s',
                        fd_utils.get_dummy_stack(outputs=False)['outputs'])
        self.assertIsNone(vnf_dict['mgmt_ip_address'])

    def test_heal_wait_failed_with_retries_0(self):
        self._response_in_wait_until_stack_ready(["UPDATE_IN_PROGRESS"])
        vnf_dict = utils.get_dummy_vnf(status='PENDING_HEAL',
                                       instance_id=self.instance_uuid)
        self.assertRaises(vnfm.VNFHealWaitFailed,
                          self.openstack.heal_wait,
                          None, None, vnf_dict,
                          None)

    def test_heal_wait_failed_stack_retries_not_0(self):
        self._response_in_wait_until_stack_ready(["UPDATE_IN_PROGRESS",
                                                 "FAILED"])
        vnf_dict = utils.get_dummy_vnf(status='PENDING_HEAL',
                                       instance_id=self.instance_uuid)
        self.assertRaises(vnfm.VNFHealWaitFailed,
                          self.openstack.heal_wait,
                          None, None, vnf_dict,
                          None)

    def _responses_in_resource_event_list(self, dummy_event):
        # response for heat_client's resource_event_list()
        url = self.heat_url + '/stacks/' + self.instance_uuid
        json = {'stack': [fd_utils.get_dummy_stack()]}
        self.requests_mock.register_uri('GET', url, json=json,
                                        headers=self.json_headers)
        url = self.heat_url + '/stacks/' + self.instance_uuid + (
            '/myStack/60f83b5e/resources/SP1_scale_out/events?limit=1&sort_dir'
            '=desc&sort_keys=event_time')
        json = {'events': [dummy_event]}
        self.requests_mock.register_uri('GET', url, json=json,
                                        headers=self.json_headers)

    def test_scale(self):
        dummy_event = fd_utils.get_dummy_event()
        self._responses_in_resource_event_list(dummy_event)
        # response for heat_client's resource_signal()
        url = self.heat_url + '/stacks/' + self.instance_uuid + (
            '/myStack/60f83b5e/resources/SP1_scale_out/signal')
        self.requests_mock.register_uri('POST', url, json={},
                                        headers=self.json_headers)
        event_id = self.openstack.scale(plugin=self, context=self.context,
                                    auth_attr=None,
                                    policy=fd_utils.get_dummy_policy_dict(),
                                    region_name=None)
        self.assertEqual(dummy_event['id'], event_id)

    def _response_in_resource_get_list(self, stack_id=None,
            resources=None):
        # response for heat_client's resource_get_list()

        if stack_id:
            url = self.heat_url + '/stacks/' + stack_id + '/resources'
        else:
            url = self.heat_url + '/stacks/' + self.stack_id + '/resources'
        resources = resources or [fd_utils.get_dummy_resource()]
        json = {'resources': resources}
        self.requests_mock.register_uri('GET', url, json=json,
                                        headers=self.json_headers)

    def _test_scale(self, resource_status):
        dummy_event = fd_utils.get_dummy_event(resource_status)
        self._responses_in_resource_event_list(dummy_event)
        self._response_in_resource_get(self.instance_uuid, res_name='G1')
        self._response_in_resource_get_list()
        self._response_in_resource_get(self.stack_id)
        self._response_in_resource_get(self.instance_uuid,
                                       res_name='SP1_group')

    def test_scale_wait_with_different_last_event_id(self):
        self._test_scale("SIGNAL_COMPLETE")
        mgmt_ip = self.openstack.scale_wait(plugin=self, context=self.context,
                                     auth_attr=None,
                                     policy=fd_utils.get_dummy_policy_dict(),
                                     region_name=None,
                                     last_event_id=uuidsentinel.
                                            non_last_event_id)
        self.assertEqual(helpers.compact_byte('{"vdu1": ["test1"]}'),
                         mgmt_ip)

    @ddt.data("SIGNAL_COMPLETE", "CREATE_COMPLETE")
    def test_scale_wait_with_same_last_event_id(self, resource_status):
        self._test_scale(resource_status)
        mgmt_ip = self.openstack.scale_wait(plugin=self,
                                context=self.context,
                                auth_attr=None,
                                policy=fd_utils.get_dummy_policy_dict(),
                                region_name=None,
                                last_event_id=fd_utils.get_dummy_event()['id'])
        self.assertEqual(helpers.compact_byte('{"vdu1": ["test1"]}'),
                         mgmt_ip)

    @mock.patch('tacker.vnfm.infra_drivers.openstack.openstack.LOG')
    def test_scale_wait_failed_with_exception(self, mock_log):
        self._exception_response()
        self.assertRaises(vnfm.VNFScaleWaitFailed,
                          self.openstack.scale_wait,
                          plugin=self, context=self.context, auth_attr=None,
                          policy=fd_utils.get_dummy_policy_dict(),
                          region_name=None,
                          last_event_id=fd_utils.get_dummy_event()['id'])
        mock_log.warning.assert_called_once()

    def _response_in_resource_metadata(self, metadata=None):
        # response for heat_client's resource_metadata()
        url = self.heat_url + '/stacks/' + self.instance_uuid + \
            '/myStack/60f83b5e/resources/SP1_scale_out/metadata'
        json = {'metadata': {'scaling_in_progress': metadata}}
        return self.requests_mock.register_uri('GET', url, json=json,
                                        headers=self.json_headers)

    def test_scale_wait_failed_with_stack_retries_0(self):
        dummy_event = fd_utils.get_dummy_event("CREATE_IN_PROGRESS")
        self._responses_in_resource_event_list(dummy_event)
        self._response_in_resource_metadata(True)
        self.assertRaises(vnfm.VNFScaleWaitFailed,
                          self.openstack.scale_wait,
                          plugin=self, context=self.context, auth_attr=None,
                          policy=fd_utils.get_dummy_policy_dict(),
                          region_name=None,
                          last_event_id=dummy_event['id'])
        self.mock_log.warning.assert_called_once()

    def test_scale_wait_without_resource_metadata(self):
        dummy_event = fd_utils.get_dummy_event("CREATE_IN_PROGRESS")
        self._responses_in_resource_event_list(dummy_event)
        self._response_in_resource_metadata()
        self._response_in_resource_get(self.instance_uuid, res_name='G1')
        self._response_in_resource_get_list()
        self._response_in_resource_get(self.stack_id)
        self._response_in_resource_get(self.instance_uuid,
                                       res_name='SP1_group')
        mgmt_ip = self.openstack.scale_wait(plugin=self, context=self.context,
                                  auth_attr=None,
                                  policy=fd_utils.get_dummy_policy_dict(),
                                  region_name=None,
                                  last_event_id=fd_utils.get_dummy_event()
                                  ['id'])
        error_reason = ('When signal occurred within cool down '
                        'window, no events generated from heat, '
                        'so ignore it')
        self.mock_log.warning.assert_called_once_with(error_reason)
        self.assertEqual(b'{"vdu1": ["test1"]}', mgmt_ip)

    def _responses_in_create_image(self, multiple_responses=False):
        # response for glance_client's create()
        json = fd_utils.get_fake_glance_image_dict()
        url = os.path.join(self.glance_url, 'images')
        if multiple_responses:
            return self.requests_mock.register_uri(
                'POST', url, [{'json': json, 'status_code': 201,
                               'headers': self.json_headers},
                              {'exc': requests.exceptions.ConnectTimeout}])
        else:
            return self.requests_mock.register_uri('POST', url, json=json,
                                            headers=self.json_headers)

    def _responses_in_import_image(self, raise_exception=False):
        # response for glance_client's import()
        json = fd_utils.get_fake_glance_image_dict()
        url = os.path.join(
            self.glance_url, 'images', uuidsentinel.image_id, 'import')

        if raise_exception:
            return self.requests_mock.register_uri('POST', url,
                exc=requests.exceptions.ConnectTimeout)
        else:
            return self.requests_mock.register_uri('POST', url, json=json,
                headers=self.json_headers)

    def _responses_in_get_image(self, image_path=None, status='active',
                                hash_value='hash'):
        # response for glance_client's import()
        json = fd_utils.get_fake_glance_image_dict(image_path=image_path,
                                                   status=status,
                                                   hash_value=hash_value)
        url = os.path.join(
            self.glance_url, 'images', uuidsentinel.image_id)
        return self.requests_mock.register_uri('GET', url, json=json,
                                        headers=self.json_headers)

    def _responses_in_upload_image(self, image_path=None, status='active',
                                   hash_value='hash'):
        # response for glance_client's upload()
        json = fd_utils.get_fake_glance_image_dict(image_path=image_path,
                                                   status=status,
                                                   hash_value=hash_value)
        url = os.path.join(
            self.glance_url, 'images', uuidsentinel.image_id, 'file')
        return self.requests_mock.register_uri('PUT', url, json=json,
                                        headers=self.json_headers)

    def test_pre_instantiation_vnf_image_with_file(self):
        vnf_instance = fd_utils.get_vnf_instance_object()

        # Create a temporary file as the openstacksdk will access it for
        # calculating the hash value.
        image_fd, image_path = tempfile.mkstemp()
        vnf_software_image = fd_utils.get_vnf_software_image_object(
            image_path=image_path)
        vnf_software_images = {'node_name': vnf_software_image}

        upload_image_url = self._responses_in_upload_image(image_path)
        create_image_url = self._responses_in_create_image()
        get_image_url = self._responses_in_get_image(image_path)

        vnf_resources = self.openstack.pre_instantiation_vnf(
            self.context, vnf_instance, None, vnf_software_images)

        image_resource = vnf_resources['node_name'][0]

        os.close(image_fd)
        os.remove(image_path)

        # Asserting the response as per the data given in the fake objects.
        self.assertEqual(image_resource.resource_name,
                         'test-image')
        self.assertEqual(image_resource.resource_status,
                         'CREATED')
        self.assertEqual(image_resource.resource_type,
                         'image')
        self.assertEqual(image_resource.vnf_instance_id,
                         vnf_instance.id)
        self.assertEqual(upload_image_url.call_count, 1)
        self.assertEqual(create_image_url.call_count, 1)
        self.assertEqual(get_image_url.call_count, 2)

    @mock.patch('tacker.common.utils.is_url', mock.MagicMock(
        return_value=True))
    def test_pre_instantiation_vnf_image_with_url(self):
        image_path = "http://fake-url.net"
        vnf_instance = fd_utils.get_vnf_instance_object()

        vnf_software_image = fd_utils.get_vnf_software_image_object(
            image_path=image_path)
        vnf_software_images = {'node_name': vnf_software_image}
        create_image_url = self._responses_in_create_image(image_path)
        import_image_url = self._responses_in_import_image()
        get_image_url = self._responses_in_get_image(image_path)

        vnf_resources = self.openstack.pre_instantiation_vnf(
            self.context, vnf_instance, None, vnf_software_images)

        image_resource = vnf_resources['node_name'][0]

        # Asserting the response as per the data given in the fake objects.
        self.assertEqual(image_resource.resource_name,
                         'test-image')
        self.assertEqual(image_resource.resource_status,
                         'CREATED')
        self.assertEqual(image_resource.resource_type,
                         'image')
        self.assertEqual(image_resource.vnf_instance_id,
                         vnf_instance.id)
        self.assertEqual(create_image_url.call_count, 1)
        self.assertEqual(import_image_url.call_count, 1)
        self.assertEqual(get_image_url.call_count, 1)

    @ddt.data(False, True)
    def test_pre_instantiation_vnf_failed_in_image_creation(
            self, exception_in_delete_image):
        vnf_instance = fd_utils.get_vnf_instance_object()

        vnf_software_image = fd_utils.get_vnf_software_image_object()
        vnf_software_images = {'node_name1': vnf_software_image,
                               'node_name2': vnf_software_image}
        # exception will occur in second iteration of image creation.
        create_image_url = self._responses_in_create_image(
            multiple_responses=True)
        import_image_url = self._responses_in_import_image()
        get_image_url = self._responses_in_get_image()
        delete_image_url = self._response_in_delete_image(
            uuidsentinel.image_id, exception=exception_in_delete_image)
        self.assertRaises(exceptions.VnfPreInstantiationFailed,
                          self.openstack.pre_instantiation_vnf,
                          self.context, vnf_instance, None,
                          vnf_software_images)
        self.assertEqual(create_image_url.call_count, 3)
        self.assertEqual(import_image_url.call_count, 1)
        self.assertEqual(get_image_url.call_count, 1)

        delete_call_count = 2 if exception_in_delete_image else 1
        self.assertEqual(delete_image_url.call_count, delete_call_count)

    @ddt.data(False, True)
    def test_pre_instantiation_vnf_failed_in_image_upload(
            self, exception_in_delete_image):
        vnf_instance = fd_utils.get_vnf_instance_object()
        image_path = '/non/existent/file'
        software_image_update = {'image_path': image_path}
        vnf_software_image = fd_utils.get_vnf_software_image_object(
            **software_image_update)
        vnf_software_images = {'node_name1': vnf_software_image,
                               'node_name2': vnf_software_image}

        # exception will occur in second iteration of image creation.

        # No urls are accessed in this case because openstacksdk fails to
        # access the file when it wants to calculate the hash.
        self._responses_in_create_image(multiple_responses=True)
        self._responses_in_upload_image(image_path)
        self._responses_in_get_image()
        self._response_in_delete_image(uuidsentinel.image_id,
            exception=exception_in_delete_image)
        self.assertRaises(exceptions.VnfPreInstantiationFailed,
                          self.openstack.pre_instantiation_vnf,
                          self.context, vnf_instance, None,
                          vnf_software_images)

    def test_pre_instantiation_vnf_failed_with_mismatch_in_hash_value(self):
        vnf_instance = fd_utils.get_vnf_instance_object()

        vnf_software_image = fd_utils.get_vnf_software_image_object()
        vnf_software_images = {'node_name1': vnf_software_image,
                               'node_name2': vnf_software_image}
        # exception will occur in second iteration of image creation.
        create_image_url = self._responses_in_create_image(
            multiple_responses=True)
        import_image_url = self._responses_in_import_image()
        get_image_url = self._responses_in_get_image(
            hash_value='diff-hash-value')
        delete_image_url = self._response_in_delete_image(
            uuidsentinel.image_id)
        self.assertRaises(exceptions.VnfPreInstantiationFailed,
                          self.openstack.pre_instantiation_vnf,
                          self.context, vnf_instance, None,
                          vnf_software_images)
        self.assertEqual(create_image_url.call_count, 1)
        self.assertEqual(import_image_url.call_count, 1)
        self.assertEqual(get_image_url.call_count, 1)
        self.assertEqual(delete_image_url.call_count, 1)

    def test_pre_instantiation_vnf_with_image_create_wait_failed(self):
        vnf_instance = fd_utils.get_vnf_instance_object()

        vnf_software_image = fd_utils.get_vnf_software_image_object()
        vnf_software_images = {'node_name1': vnf_software_image,
                               'node_name2': vnf_software_image}
        # exception will occurs in second iteration of image creation.
        create_image_url = self._responses_in_create_image()
        import_image_url = self._responses_in_import_image()
        get_image_url = self._responses_in_get_image(status='pending_create')
        self.assertRaises(exceptions.VnfPreInstantiationFailed,
                          self.openstack.pre_instantiation_vnf,
                          self.context, vnf_instance, None,
                          vnf_software_images)
        self.assertEqual(create_image_url.call_count, 1)
        self.assertEqual(import_image_url.call_count, 1)
        self.assertEqual(get_image_url.call_count, 10)

    def _exception_response_in_import_image(self):
        url = os.path.join(self.glance_url, 'images', uuidsentinel.image_id,
                           'import')
        return self.requests_mock.register_uri(
            'POST', url, exc=requests.exceptions.ConnectTimeout)

    def _response_in_delete_image(self, resource_id, exception=False):
        # response for glance_client's delete()
        url = os.path.join(
            self.glance_url, 'images', resource_id)
        if exception:
            return self.requests_mock.register_uri(
                'DELETE', url, exc=requests.exceptions.ConnectTimeout)
        else:
            return self.requests_mock.register_uri('DELETE', url, json={},
                                            status_code=200,
                                            headers=self.json_headers)

    @ddt.data(True, False)
    def test_pre_instantiation_vnf_failed_in_image_import(
            self, exception_in_delete):
        vnf_instance = fd_utils.get_vnf_instance_object()

        vnf_software_image = fd_utils.get_vnf_software_image_object()
        vnf_software_images = {'node_name': vnf_software_image}

        create_image_url = self._responses_in_create_image()
        import_image_exc_url = self._responses_in_import_image(
            raise_exception=True)
        delete_image_url = self._response_in_delete_image(
            uuidsentinel.image_id, exception_in_delete)
        self.assertRaises(exceptions.VnfPreInstantiationFailed,
                          self.openstack.pre_instantiation_vnf,
                          self.context, vnf_instance, None,
                          vnf_software_images)
        self.assertEqual(create_image_url.call_count, 1)
        self.assertEqual(import_image_exc_url.call_count, 2)
        delete_call_count = 2 if exception_in_delete else 1
        self.assertEqual(delete_image_url.call_count, delete_call_count)

    @mock.patch('tacker.vnfm.infra_drivers.openstack.openstack.LOG')
    def test_delete_vnf_instance_resource(self, mock_log):
        vnf_instance = fd_utils.get_vnf_instance_object()
        vnf_resource = fd_utils.get_vnf_resource_object()

        delete_image_url = self._response_in_delete_image(
            vnf_resource.resource_identifier)
        self.openstack.delete_vnf_instance_resource(
            self.context, vnf_instance, None, vnf_resource)
        mock_log.info.assert_called()
        self.assertEqual(delete_image_url.call_count, 1)

    @mock.patch('tacker.vnfm.infra_drivers.openstack.openstack.LOG')
    def test_delete_vnf_instance_resource_failed_with_exception(
            self, mock_log):
        vnf_instance = fd_utils.get_vnf_instance_object()
        vnf_resource = fd_utils.get_vnf_resource_object()

        delete_image_url = self._response_in_delete_image(
            vnf_resource.resource_identifier, exception=True)
        self.openstack.delete_vnf_instance_resource(
            self.context, vnf_instance, None, vnf_resource)
        mock_log.info.assert_called()
        self.assertEqual(delete_image_url.call_count, 2)

    @mock.patch('tacker.vnfm.infra_drivers.openstack.translate_template.'
                'TOSCAToHOT._get_unsupported_resource_props')
    def test_instantiate_vnf(self, mock_get_unsupported_resource_props):
        vim_connection_info = fd_utils.get_vim_connection_info_object()
        inst_req_info = fd_utils.get_instantiate_vnf_request()
        vnfd_dict = fd_utils.get_vnfd_dict()
        grant_response = fd_utils.get_grant_response_dict()

        url = os.path.join(self.heat_url, 'stacks')
        self.requests_mock.register_uri(
            'POST', url, json={'stack': fd_utils.get_dummy_stack()},
            headers=self.json_headers)

        instance_id = self.openstack.instantiate_vnf(
            self.context, None, vnfd_dict, vim_connection_info,
            inst_req_info, grant_response)

        self.assertEqual(uuidsentinel.instance_id, instance_id)

    def _responses_in_stack_list(self, instance_id, resources=None):

        resources = resources or []
        url = os.path.join(self.heat_url, 'stacks', instance_id, 'resources')
        self.requests_mock.register_uri('GET', url,
            json={'resources': resources}, headers=self.json_headers)

        response_list = [{'json': {'stacks': [fd_utils.get_dummy_stack(
            attrs={'parent': uuidsentinel.instance_id})]}},
            {'json': {'stacks': [fd_utils.get_dummy_stack()]}}]

        url = os.path.join(self.heat_url, 'stacks?owner_id=' +
                           instance_id + '&show_nested=True')
        self.requests_mock.register_uri('GET', url, response_list)

    def test_post_vnf_instantiation(self):
        v_s_resource_info = fd_utils.get_virtual_storage_resource_info(
            desc_id="storage1", set_resource_id=False)

        storage_resource_ids = [v_s_resource_info.id]
        vnfc_resource_info = fd_utils.get_vnfc_resource_info(vdu_id="VDU_VNF",
            storage_resource_ids=storage_resource_ids, set_resource_id=False)

        v_l_resource_info = fd_utils.get_virtual_link_resource_info(
            vnfc_resource_info.vnfc_cp_info[0].vnf_link_port_id,
            vnfc_resource_info.vnfc_cp_info[0].id)

        inst_vnf_info = fd_utils.get_vnf_instantiated_info(
            virtual_storage_resource_info=[v_s_resource_info],
            vnf_virtual_link_resource_info=[v_l_resource_info],
            vnfc_resource_info=[vnfc_resource_info])

        vnf_instance = fd_utils.get_vnf_instance_object(
            instantiated_vnf_info=inst_vnf_info)

        vim_connection_info = fd_utils.get_vim_connection_info_object()
        resources = [{'resource_name': vnfc_resource_info.vdu_id,
            'resource_type': vnfc_resource_info.compute_resource.
                vim_level_resource_type,
            'physical_resource_id': uuidsentinel.vdu_resource_id},
            {'resource_name': v_s_resource_info.virtual_storage_desc_id,
            'resource_type': v_s_resource_info.storage_resource.
                vim_level_resource_type,
            'physical_resource_id': uuidsentinel.storage_resource_id},
            {'resource_name': vnfc_resource_info.vnfc_cp_info[0].cpd_id,
            'resource_type': inst_vnf_info.vnf_virtual_link_resource_info[0].
                vnf_link_ports[0].resource_handle.vim_level_resource_type,
            'physical_resource_id': uuidsentinel.cp1_resource_id}]

        self._responses_in_stack_list(inst_vnf_info.instance_id,
            resources=resources)
        self.openstack.post_vnf_instantiation(
            self.context, vnf_instance, vim_connection_info)
        self.assertEqual(vnf_instance.instantiated_vnf_info.
            vnfc_resource_info[0].metadata['stack_id'],
            inst_vnf_info.instance_id)

        # Check if vnfc resource "VDU_VNF" is set with resource_id
        self.assertEqual(uuidsentinel.vdu_resource_id,
            vnf_instance.instantiated_vnf_info.vnfc_resource_info[0].
            compute_resource.resource_id)

        # Check if virtual storage resource "storage1" is set with resource_id
        self.assertEqual(uuidsentinel.storage_resource_id,
            vnf_instance.instantiated_vnf_info.
            virtual_storage_resource_info[0].storage_resource.resource_id)

        # Check if virtual link port "CP1" is set with resource_id
        self.assertEqual(uuidsentinel.cp1_resource_id,
            vnf_instance.instantiated_vnf_info.
            vnf_virtual_link_resource_info[0].vnf_link_ports[0].
            resource_handle.resource_id)

    def test_post_vnf_instantiation_with_ext_managed_virtual_link(self):
        v_s_resource_info = fd_utils.get_virtual_storage_resource_info(
            desc_id="storage1", set_resource_id=False)

        storage_resource_ids = [v_s_resource_info.id]
        vnfc_resource_info = fd_utils.get_vnfc_resource_info(vdu_id="VDU_VNF",
            storage_resource_ids=storage_resource_ids, set_resource_id=False)

        v_l_resource_info = fd_utils.get_virtual_link_resource_info(
            vnfc_resource_info.vnfc_cp_info[0].vnf_link_port_id,
            vnfc_resource_info.vnfc_cp_info[0].id,
            desc_id='ExternalVL1')

        ext_managed_v_l_resource_info = \
            fd_utils.get_ext_managed_virtual_link_resource_info(
                uuidsentinel.virtual_link_port_id,
                uuidsentinel.vnfc_cp_info_id,
                desc_id='ExternalVL1')

        inst_vnf_info = fd_utils.get_vnf_instantiated_info(
            virtual_storage_resource_info=[v_s_resource_info],
            vnf_virtual_link_resource_info=[v_l_resource_info],
            vnfc_resource_info=[vnfc_resource_info],
            ext_managed_virtual_link_info=[ext_managed_v_l_resource_info])

        vnf_instance = fd_utils.get_vnf_instance_object(
            instantiated_vnf_info=inst_vnf_info)

        vim_connection_info = fd_utils.get_vim_connection_info_object()
        resources = [{'resource_name': vnfc_resource_info.vdu_id,
            'resource_type': vnfc_resource_info.compute_resource.
                vim_level_resource_type,
            'physical_resource_id': uuidsentinel.vdu_resource_id},
            {'resource_name': v_s_resource_info.virtual_storage_desc_id,
            'resource_type': v_s_resource_info.storage_resource.
                vim_level_resource_type,
            'physical_resource_id': uuidsentinel.storage_resource_id},
            {'resource_name': vnfc_resource_info.vnfc_cp_info[0].cpd_id,
            'resource_type': inst_vnf_info.vnf_virtual_link_resource_info[0].
                vnf_link_ports[0].resource_handle.vim_level_resource_type,
            'physical_resource_id': uuidsentinel.cp1_resource_id},
            {'resource_name': v_l_resource_info.vnf_virtual_link_desc_id,
            'resource_type': v_l_resource_info.network_resource.
                vim_level_resource_type,
            'physical_resource_id': uuidsentinel.v_l_resource_info_id}]
        self._responses_in_stack_list(inst_vnf_info.instance_id,
            resources=resources)
        self.openstack.post_vnf_instantiation(
            self.context, vnf_instance, vim_connection_info)
        self.assertEqual(vnf_instance.instantiated_vnf_info.
            vnfc_resource_info[0].metadata['stack_id'],
            inst_vnf_info.instance_id)

        # Check if vnfc resource "VDU_VNF" is set with resource_id
        self.assertEqual(uuidsentinel.vdu_resource_id,
            vnf_instance.instantiated_vnf_info.vnfc_resource_info[0].
            compute_resource.resource_id)

        # Check if virtual storage resource "storage1" is set with resource_id
        self.assertEqual(uuidsentinel.storage_resource_id,
            vnf_instance.instantiated_vnf_info.
            virtual_storage_resource_info[0].storage_resource.resource_id)

        # Check if virtual link port "CP1" is set with resource_id
        self.assertEqual(uuidsentinel.cp1_resource_id,
            vnf_instance.instantiated_vnf_info.
            vnf_virtual_link_resource_info[0].vnf_link_ports[0].
            resource_handle.resource_id)

        # Check if ext managed virtual link port is set with resource_id
        self.assertEqual(uuidsentinel.cp1_resource_id,
            vnf_instance.instantiated_vnf_info.
            ext_managed_virtual_link_info[0].vnf_link_ports[0].
            resource_handle.resource_id)

    def test_heal_vnf_instance(self):
        v_s_resource_info = fd_utils.get_virtual_storage_resource_info(
            desc_id="storage1")

        storage_resource_ids = [v_s_resource_info.id]
        vnfc_resource_info = fd_utils.get_vnfc_resource_info(vdu_id="VDU_VNF",
            storage_resource_ids=storage_resource_ids)

        inst_vnf_info = fd_utils.get_vnf_instantiated_info(
            virtual_storage_resource_info=[v_s_resource_info],
            vnfc_resource_info=[vnfc_resource_info])

        vnf_instance = fd_utils.get_vnf_instance_object(
            instantiated_vnf_info=inst_vnf_info)

        vim_connection_info = fd_utils.get_vim_connection_info_object()

        heal_vnf_request = objects.HealVnfRequest(
            vnfc_instance_id=[vnfc_resource_info.id],
            cause="healing request")

        # Mock various heat APIs that will be called by heatclient
        # during the process of heal_vnf.
        resources = [{
            'resource_name': vnfc_resource_info.vdu_id,
            'resource_type': vnfc_resource_info.compute_resource.
            vim_level_resource_type,
            'physical_resource_id': vnfc_resource_info.compute_resource.
            resource_id}, {
            'resource_name': v_s_resource_info.virtual_storage_desc_id,
            'resource_type': v_s_resource_info.storage_resource.
            vim_level_resource_type,
            'physical_resource_id': v_s_resource_info.storage_resource.
            resource_id}]

        self._response_in_stack_get(inst_vnf_info.instance_id)
        self._response_in_resource_get_list(inst_vnf_info.instance_id,
                resources=resources)
        self._responses_in_stack_list(inst_vnf_info.instance_id,
            resources=resources)
        self._response_in_stack_update(inst_vnf_info.instance_id)
        self._response_resource_mark_unhealthy(inst_vnf_info.instance_id,
                resources=resources)

        self.openstack.heal_vnf(
            self.context, vnf_instance, vim_connection_info, heal_vnf_request)

        history = self.requests_mock.request_history
        patch_req = [req.url for req in history if req.method == 'PATCH']
        # Total 3 times patch should be called, 2 for marking resources
        # as unhealthy, and 1 for updating stack
        self.assertEqual(3, len(patch_req))

    def test_heal_vnf_instance_resource_mark_unhealthy_error(self):
        vnfc_resource_info = fd_utils.get_vnfc_resource_info(vdu_id="VDU_VNF")

        inst_vnf_info = fd_utils.get_vnf_instantiated_info(
            vnfc_resource_info=[vnfc_resource_info])

        vnf_instance = fd_utils.get_vnf_instance_object(
            instantiated_vnf_info=inst_vnf_info)

        vim_connection_info = fd_utils.get_vim_connection_info_object()

        heal_vnf_request = objects.HealVnfRequest(
            vnfc_instance_id=[vnfc_resource_info.id],
            cause="healing request")

        # Mock various heat APIs that will be called by heatclient
        # during the process of heal_vnf.
        resources = [{
            'resource_name': vnfc_resource_info.vdu_id,
            'resource_type': vnfc_resource_info.compute_resource.
            vim_level_resource_type,
            'physical_resource_id': vnfc_resource_info.compute_resource.
            resource_id}]

        self._response_in_stack_get(inst_vnf_info.instance_id)
        self._response_in_resource_get_list(inst_vnf_info.instance_id,
                resources=resources)
        self._responses_in_stack_list(inst_vnf_info.instance_id,
            resources=resources)
        self._response_resource_mark_unhealthy(inst_vnf_info.instance_id,
                resources=resources, raise_exception=True)

        result = self.assertRaises(exceptions.VnfHealFailed,
                    self.openstack.heal_vnf, self.context, vnf_instance,
                    vim_connection_info, heal_vnf_request)

        expected_msg = ("Failed to mark stack '%(id)s' resource as unhealthy "
            "for resource '%(resource_name)s'") % {
            'id': inst_vnf_info.instance_id,
            'resource_name': resources[0]['resource_name']}
        self.assertIn(expected_msg, str(result))

        history = self.requests_mock.request_history
        patch_req = [req.url for req in history if req.method == 'PATCH']
        # only one time patch method be called for marking vdu resource
        # as unhealthy
        self.assertEqual(1, len(patch_req))

    def test_heal_vnf_instance_incorrect_stack_status(self):
        inst_vnf_info = fd_utils.get_vnf_instantiated_info()

        vnf_instance = fd_utils.get_vnf_instance_object(
            instantiated_vnf_info=inst_vnf_info)

        vim_connection_info = fd_utils.get_vim_connection_info_object()

        heal_vnf_request = objects.HealVnfRequest(
            vnfc_instance_id=[uuidsentinel.vnfc_resource_id],
            cause="healing request")

        # Mock various heat APIs that will be called by heatclient
        # during the process of heal_vnf.
        self._response_in_stack_get(inst_vnf_info.instance_id,
                stack_status='UPDATE_IN_PROGRESS')

        result = self.assertRaises(exceptions.VnfHealFailed,
            self.openstack.heal_vnf, self.context, vnf_instance,
            vim_connection_info, heal_vnf_request)

        expected_msg = ("Healing of vnf instance %s is possible only when "
                        "stack %s status is CREATE_COMPLETE,UPDATE_COMPLETE, "
                        "current stack status is UPDATE_IN_PROGRESS")
        self.assertIn(expected_msg % (vnf_instance.id,
            inst_vnf_info.instance_id), str(result))

    def test_heal_vnf_wait(self):
        inst_vnf_info = fd_utils.get_vnf_instantiated_info()

        vnf_instance = fd_utils.get_vnf_instance_object(
            instantiated_vnf_info=inst_vnf_info)

        vim_connection_info = fd_utils.get_vim_connection_info_object()

        # Mock various heat APIs that will be called by heatclient
        # during the process of heal_vnf_wait.
        self._response_in_wait_until_stack_ready(["UPDATE_IN_PROGRESS",
                                                 "UPDATE_COMPLETE"])

        stack = self.openstack.heal_vnf_wait(
            self.context, vnf_instance, vim_connection_info)
        self.assertEqual('UPDATE_COMPLETE', stack.stack_status)

    def test_heal_vnf_wait_fail(self):
        inst_vnf_info = fd_utils.get_vnf_instantiated_info()

        vnf_instance = fd_utils.get_vnf_instance_object(
            instantiated_vnf_info=inst_vnf_info)

        vim_connection_info = fd_utils.get_vim_connection_info_object()

        # Mock various heat APIs that will be called by heatclient
        # during the process of heal_vnf_wait.
        self._response_in_wait_until_stack_ready(["UPDATE_IN_PROGRESS"])
        self.openstack.STACK_RETRIES = 1
        result = self.assertRaises(vnfm.VNFHealWaitFailed,
            self.openstack.heal_vnf_wait, self.context, vnf_instance,
            vim_connection_info)

        expected_msg = ("VNF Heal action is not completed within 10 seconds "
                       "on stack %s") % inst_vnf_info.instance_id
        self.assertIn(expected_msg, str(result))

    def test_post_heal_vnf(self):
        v_s_resource_info = fd_utils.get_virtual_storage_resource_info(
            desc_id="storage1")

        storage_resource_ids = [v_s_resource_info.id]
        vnfc_resource_info = fd_utils.get_vnfc_resource_info(vdu_id="VDU_VNF",
            storage_resource_ids=storage_resource_ids)

        inst_vnf_info = fd_utils.get_vnf_instantiated_info(
            virtual_storage_resource_info=[v_s_resource_info],
            vnfc_resource_info=[vnfc_resource_info])

        vnfc_resource_info.metadata['stack_id'] = inst_vnf_info.instance_id
        vnf_instance = fd_utils.get_vnf_instance_object(
            instantiated_vnf_info=inst_vnf_info)

        vim_connection_info = fd_utils.get_vim_connection_info_object()

        heal_vnf_request = objects.HealVnfRequest(
            vnfc_instance_id=[vnfc_resource_info.id],
            cause="healing request")

        # Change the physical_resource_id of both the resources, so
        # that we can check it's updated in vnf instance after
        # post_heal_vnf call.
        resources = [{
            'resource_name': vnfc_resource_info.vdu_id,
            'resource_type': vnfc_resource_info.compute_resource.
            vim_level_resource_type,
            'physical_resource_id': uuidsentinel.compute_resource_id_new}, {
            'resource_name': v_s_resource_info.virtual_storage_desc_id,
            'resource_type': v_s_resource_info.storage_resource.
            vim_level_resource_type,
            'physical_resource_id': uuidsentinel.storage_resource_id_new}]

        # Mock various heat APIs that will be called by heatclient
        # during the process of heal_vnf.
        self._responses_in_stack_list(inst_vnf_info.instance_id,
            resources=resources)

        v_s_resource_info_old = v_s_resource_info.obj_clone()
        vnfc_resource_info_old = vnfc_resource_info.obj_clone()

        self.openstack.post_heal_vnf(self.context, vnf_instance,
            vim_connection_info, heal_vnf_request)

        vnfc_resource_info_new = vnf_instance.instantiated_vnf_info.\
            vnfc_resource_info[0]
        v_s_resource_info_new = vnf_instance.instantiated_vnf_info.\
            virtual_storage_resource_info[0]

        # Compare the resource_id, it should be updated with the new ones.
        self.assertNotEqual(vnfc_resource_info_old.compute_resource.
            resource_id, vnfc_resource_info_new.compute_resource.resource_id)
        self.assertEqual(uuidsentinel.compute_resource_id_new,
            vnfc_resource_info_new.compute_resource.resource_id)

        self.assertNotEqual(v_s_resource_info_old.storage_resource.resource_id,
                v_s_resource_info_new.storage_resource.resource_id)
        self.assertEqual(uuidsentinel.storage_resource_id_new,
            v_s_resource_info_new.storage_resource.resource_id)

    def test_post_heal_vnf_fail(self):
        vnfc_resource_info = fd_utils.get_vnfc_resource_info()

        inst_vnf_info = fd_utils.get_vnf_instantiated_info(
            vnfc_resource_info=[vnfc_resource_info])

        vnfc_resource_info.metadata['stack_id'] = uuidsentinel.stack_id
        vnf_instance = fd_utils.get_vnf_instance_object(
            instantiated_vnf_info=inst_vnf_info)

        vim_connection_info = fd_utils.get_vim_connection_info_object()

        heal_vnf_request = objects.HealVnfRequest(
            vnfc_instance_id=[vnfc_resource_info.id],
            cause="healing request")

        # Change the physical_resource_id of both the resources, so
        # that we can check it's updated in vnf instance after
        # post_heal_vnf call.
        resources = [{
            'resource_name': vnfc_resource_info.vdu_id,
            'resource_type': vnfc_resource_info.compute_resource.
            vim_level_resource_type,
            'physical_resource_id': uuidsentinel.compute_resource_id_new}]

        # Mock various heat APIs that will be called by heatclient
        # during the process of heal_vnf.
        self._responses_in_stack_list(inst_vnf_info.instance_id,
            resources=resources)

        result = self.assertRaises(exceptions.VnfHealFailed,
            self.openstack.post_heal_vnf, self.context, vnf_instance,
            vim_connection_info, heal_vnf_request)

        expected_msg = ("Heal Vnf failed for vnf %s, error: Failed to find "
                        "stack_id %s") % (vnf_instance.id,
                        uuidsentinel.stack_id)
        self.assertEqual(expected_msg, str(result))
