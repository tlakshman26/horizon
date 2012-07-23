# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Nebula, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
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

from django import http
from django.core.urlresolvers import reverse
from django.utils.datastructures import SortedDict
from mox import IsA
from novaclient import exceptions as novaclient_exceptions

from horizon import api
from horizon import test


class InstanceViewTest(test.BaseAdminViewTests):
    @test.create_stubs({api.nova: ('flavor_list', 'server_list',),
                        api.keystone: ('tenant_list',)})
    def test_index(self):
        servers = self.servers.list()
        flavors = self.flavors.list()
        tenants = self.tenants.list()
        api.keystone.tenant_list(IsA(http.HttpRequest), admin=True).\
                                 AndReturn(tenants)
        api.nova.server_list(IsA(http.HttpRequest),
                             all_tenants=True).AndReturn(servers)
        api.nova.flavor_list(IsA(http.HttpRequest)).AndReturn(flavors)
        self.mox.ReplayAll()

        res = self.client.get(reverse('horizon:syspanel:instances:index'))
        self.assertTemplateUsed(res, 'syspanel/instances/index.html')
        instances = res.context['table'].data
        self.assertItemsEqual(instances, servers)

    @test.create_stubs({api.nova: ('flavor_list', 'flavor_get',
                                    'server_list',),
                        api.keystone: ('tenant_list',)})
    def test_index_flavor_list_exception(self):
        servers = self.servers.list()
        tenants = self.tenants.list()
        flavors = self.flavors.list()
        full_flavors = SortedDict([(f.id, f) for f in flavors])

        api.nova.server_list(IsA(http.HttpRequest),
                             all_tenants=True).AndReturn(servers)
        api.nova.flavor_list(IsA(http.HttpRequest)). \
                            AndRaise(self.exceptions.nova)
        api.keystone.tenant_list(IsA(http.HttpRequest), admin=True).\
                                 AndReturn(tenants)
        for server in servers:
            api.nova.flavor_get(IsA(http.HttpRequest), server.flavor["id"]). \
                                AndReturn(full_flavors[server.flavor["id"]])

        self.mox.ReplayAll()

        res = self.client.get(reverse('horizon:syspanel:instances:index'))
        self.assertTemplateUsed(res, 'syspanel/instances/index.html')
        instances = res.context['table'].data
        self.assertItemsEqual(instances, servers)

    @test.create_stubs({api.nova: ('flavor_list', 'flavor_get',
                                    'server_list',),
                        api.keystone: ('tenant_list',)})
    def test_index_flavor_get_exception(self):
        servers = self.servers.list()
        flavors = self.flavors.list()
        tenants = self.tenants.list()
        max_id = max([int(flavor.id) for flavor in flavors])
        for server in servers:
            max_id += 1
            server.flavor["id"] = max_id

        api.nova.server_list(IsA(http.HttpRequest),
                             all_tenants=True).AndReturn(servers)
        api.nova.flavor_list(IsA(http.HttpRequest)). \
                            AndReturn(flavors)
        api.keystone.tenant_list(IsA(http.HttpRequest), admin=True).\
                                 AndReturn(tenants)
        for server in servers:
            api.nova.flavor_get(IsA(http.HttpRequest), server.flavor["id"]). \
                                AndRaise(self.exceptions.nova)
        self.mox.ReplayAll()

        res = self.client.get(reverse('horizon:syspanel:instances:index'))
        instances = res.context['table'].data
        self.assertTemplateUsed(res, 'syspanel/instances/index.html')
        self.assertMessageCount(res, error=len(servers))
        self.assertItemsEqual(instances, servers)

    @test.create_stubs({api.nova: ('server_list',)})
    def test_index_server_list_exception(self):
        api.nova.server_list(IsA(http.HttpRequest),
                             all_tenants=True).AndRaise(self.exceptions.nova)

        self.mox.ReplayAll()

        res = self.client.get(reverse('horizon:syspanel:instances:index'))
        self.assertTemplateUsed(res, 'syspanel/instances/index.html')
        self.assertEqual(len(res.context['instances_table'].data), 0)

    @test.create_stubs({api: ('server_get', 'flavor_get',),
                        api.keystone: ('tenant_get',)})
    def test_ajax_loading_instances(self):
        server = self.servers.first()
        flavor = self.flavors.list()[0]
        tenant = self.tenants.list()[0]

        api.server_get(IsA(http.HttpRequest), server.id).AndReturn(server)
        api.flavor_get(IsA(http.HttpRequest),
                       server.flavor['id']).AndReturn(flavor)
        api.keystone.tenant_get(IsA(http.HttpRequest),
                                server.tenant_id,
                                admin=True).AndReturn(tenant)
        self.mox.ReplayAll()

        url = reverse('horizon:syspanel:instances:index') + \
                "?action=row_update&table=instances&obj_id=" + server.id

        res = self.client.get(url, {},
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertTemplateUsed(res, "horizon/common/_data_table_row.html")

        self.assertContains(res, "test_tenant", 1, 200)
        self.assertContains(res, "instance-host", 1, 200)
        self.assertContains(res, "server_1", 1, 200)
        self.assertContains(res, "10.0.0.1", 1, 200)
        self.assertContains(res, "512MB RAM | 1 VCPU | 0 Disk", 1, 200)
        self.assertContains(res, "Active", 1, 200)
        self.assertContains(res, "Running", 1, 200)

    @test.create_stubs({api.nova: ('flavor_list', 'keypair_list',
                                    'security_group_list', 'volume_list',
                                    'volume_snapshot_list',
                                    'tenant_quota_usages', 'server_create'),
                        api.quantum: ('network_list',),
                        api.glance: ('image_list_detailed',)})
    def test_launch_post(self):
        flavor = self.flavors.first()
        image = self.images.first()
        keypair = self.keypairs.first()
        server = self.servers.first()
        volume = self.volumes.first()
        sec_group = self.security_groups.first()
        customization_script = 'user data'
        device_name = u'vda'
        volume_choice = "%s:vol" % volume.id
        block_device_mapping = {device_name: u"%s::0" % volume_choice}
        nics = [{"net-id": self.networks.first().id, "v4-fixed-ip": ''}]

        api.nova.flavor_list(IsA(http.HttpRequest)) \
                .AndReturn(self.flavors.list())
        api.nova.keypair_list(IsA(http.HttpRequest)) \
                .AndReturn(self.keypairs.list())
        api.nova.security_group_list(IsA(http.HttpRequest)) \
                .AndReturn(self.security_groups.list())
        api.glance.image_list_detailed(IsA(http.HttpRequest),
                                       filters={'is_public': True}) \
                  .AndReturn([self.images.list(), False])
        api.glance.image_list_detailed(IsA(http.HttpRequest),
                            filters={'property-owner_id': self.tenant.id}) \
                  .AndReturn([[], False])
        api.nova.volume_list(IsA(http.HttpRequest)) \
                .AndReturn(self.volumes.list())
        api.nova.volume_snapshot_list(IsA(http.HttpRequest)).AndReturn([])
        api.quantum.network_list(IsA(http.HttpRequest)) \
                .AndReturn(self.networks.list())
        api.nova.server_create(IsA(http.HttpRequest),
                               server.name,
                               image.id,
                               flavor.id,
                               keypair.name,
                               customization_script,
                               [sec_group.name],
                               block_device_mapping,
                               nics=nics,
                               instance_count=IsA(int))
        self.mox.ReplayAll()

        form_data = {'flavor': flavor.id,
                     'source_type': 'image_id',
                     'image_id': image.id,
                     'keypair': keypair.name,
                     'name': server.name,
                     'customization_script': customization_script,
                     'project_id': self.tenants.first().id,
                     'user_id': self.user.id,
                     'groups': sec_group.name,
                     'volume_type': 'volume_id',
                     'volume_id': volume_choice,
                     'device_name': device_name,
                     'network': self.networks.first().id,
                     'count': 1}
        url = reverse('horizon:syspanel:instances:launch')
        res = self.client.post(url, form_data)
        self.assertNoFormErrors(res)
        self.assertRedirectsNoFollow(res,
                 reverse('horizon:syspanel:instances:index'))
