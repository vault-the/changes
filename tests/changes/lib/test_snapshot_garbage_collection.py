from changes.config import db
from changes.testutils.cases import TestCase
from changes.models import CachedSnapshotImage
import changes.lib.snapshot_garbage_collection as gc

import datetime
import mock
import sqlalchemy


class TestSnapshotGCTestCase(TestCase):
    def setUp(self):
        """
        Used to fix the current time from datetime for the entirety of a
        single test.
        """
        self.mock_datetime = datetime.datetime.utcnow()
        super(TestSnapshotGCTestCase, self).setUp()

    def test_get_plans_for_cluster(self):
        project1 = self.create_project()
        project2 = self.create_project()
        plan1_1 = self.create_plan(project1, data={'cluster': 'cluster1'})
        plan1_2 = self.create_plan(project1, data={'cluster': 'cluster2'})
        plan2_1 = self.create_plan(project2, data={'cluster': 'cluster1'})
        plan2_2 = self.create_plan(project2)

        plans = gc.get_plans_for_cluster('cluster1')
        assert len(plans) == 2
        assert plan1_1 in plans
        assert plan2_1 in plans

    @mock.patch('changes.lib.snapshot_garbage_collection.get_plans_for_cluster')
    def test_cached_snapshot_images_gets_plans(self, get_plans):
        """More or less a metatest that verifies that the mocking
        is actually working.
        """
        project = self.create_project()
        plan = self.create_plan(project)
        snapshot = self.create_snapshot(project)

        snapshot_image = self.create_snapshot_image(snapshot, plan)
        cached_snapshot_image = self.create_cached_snapshot_image(snapshot_image)

        get_plans.return_value = []
        gc.get_cached_snapshot_images('cluster')
        get_plans.assert_called_with('cluster')

    @mock.patch('changes.lib.snapshot_garbage_collection.get_plans_for_cluster')
    def test_cached_snapshot_images_no_plans(self, get_plans):
        project = self.create_project()
        plan = self.create_plan(project)
        snapshot = self.create_snapshot(project)

        snapshot_image = self.create_snapshot_image(snapshot, plan)
        cached_snapshot_image = self.create_cached_snapshot_image(snapshot_image)

        get_plans.return_value = []

        assert gc.get_cached_snapshot_images('cluster') == []

    @mock.patch('changes.lib.snapshot_garbage_collection.get_current_datetime')
    @mock.patch('changes.lib.snapshot_garbage_collection.get_plans_for_cluster')
    def test_cached_snapshot_images_get_current_datetime(self, get_plans, get_current_datetime):
        """More or less a metatest that verifies that the mocking
        is actually working.
        """
        project = self.create_project()
        plan = self.create_plan(project)
        snapshot = self.create_snapshot(project)

        snapshot_image = self.create_snapshot_image(snapshot, plan)
        cached_snapshot_image = self.create_cached_snapshot_image(snapshot_image)

        get_plans.return_value = []
        get_current_datetime.return_value = self.mock_datetime
        gc.get_cached_snapshot_images('cluster')
        get_current_datetime.assert_any_call()

    @mock.patch('changes.lib.snapshot_garbage_collection.get_current_datetime')
    @mock.patch('changes.lib.snapshot_garbage_collection.get_plans_for_cluster')
    def test_cached_snapshot_images_all(self, get_plans, get_current_datetime):
        """
        Tests the four fundamental cases for an image:
         - No expiration date
         - Not yet expired
         - Expired
         - Not part of the plans associated with the cluster
        """
        project = self.create_project()
        plan1 = self.create_plan(project)
        plan2 = self.create_plan(project)
        plan3 = self.create_plan(project)
        plan4 = self.create_plan(project)

        get_current_datetime.return_value = self.mock_datetime
        get_plans.return_value = [plan1, plan2, plan3]

        snapshot = self.create_snapshot(project)
        snapshot_image1 = self.create_snapshot_image(snapshot, plan1)
        snapshot_image2 = self.create_snapshot_image(snapshot, plan2)
        snapshot_image3 = self.create_snapshot_image(snapshot, plan3)
        snapshot_image4 = self.create_snapshot_image(snapshot, plan4)

        self.create_cached_snapshot_image(snapshot_image1, expiration_date=None)
        self.create_cached_snapshot_image(snapshot_image2,
                expiration_date=self.mock_datetime + datetime.timedelta(0, 1))
        self.create_cached_snapshot_image(snapshot_image3,
                expiration_date=self.mock_datetime - datetime.timedelta(0, 1))
        self.create_cached_snapshot_image(snapshot_image4, expiration_date=None)

        cached_snapshot_ids = [s.id for s in gc.get_cached_snapshot_images('cluster')]

        assert len(cached_snapshot_ids) == 2
        assert snapshot_image1.id in cached_snapshot_ids
        assert snapshot_image2.id in cached_snapshot_ids

    @mock.patch('changes.lib.snapshot_garbage_collection.get_current_datetime')
    def test_cache_snapshot_images_have_no_expiration(self, get_current_datetime):
        project = self.create_project()
        snapshot = self.create_snapshot(project)
        plans = [self.create_plan(project) for _ in range(3)]
        snapshot_images = [self.create_snapshot_image(snapshot, plan) for plan in plans]
        snapshot_image_ids = [image.id for image in snapshot_images]

        get_current_datetime.return_value = self.mock_datetime

        gc.cache_snapshot(snapshot)
        assert not db.session.query(CachedSnapshotImage.query.filter(
            CachedSnapshotImage.id.in_(snapshot_image_ids),
            CachedSnapshotImage.expiration_date != None,  # NOQA
        ).exists()).scalar()

    @mock.patch('changes.lib.snapshot_garbage_collection.get_current_datetime')
    def test_cache_snapshot_images_have_no_expiration_with_old(self, get_current_datetime):
        project = self.create_project()
        old_snapshot = self.create_snapshot(project)
        snapshot = self.create_snapshot(project)
        plans = [self.create_plan(project) for _ in range(3)]

        for plan in plans:
            old_snapshot_image = self.create_snapshot_image(old_snapshot, plan)
            self.create_cached_snapshot_image(old_snapshot_image)

        snapshot_images = [self.create_snapshot_image(snapshot, plan) for plan in plans]
        snapshot_image_ids = [image.id for image in snapshot_images]

        get_current_datetime.return_value = self.mock_datetime

        gc.cache_snapshot(snapshot)
        assert not db.session.query(CachedSnapshotImage.query.filter(
            CachedSnapshotImage.id.in_(snapshot_image_ids),
            CachedSnapshotImage.expiration_date != None,  # NOQA
        ).exists()).scalar()

    @mock.patch('changes.lib.snapshot_garbage_collection.get_current_datetime')
    def test_cache_snapshot_expires_old_snapshot(self, get_current_datetime):
        project = self.create_project()
        plans = [self.create_plan(project) for _ in range(3)]

        old_snapshot = self.create_snapshot(project)
        old_snapshot_images = [self.create_snapshot_image(old_snapshot, plan) for plan in plans]
        old_snapshot_image_ids = [image.id for image in old_snapshot_images]

        snapshot = self.create_snapshot(project)
        snapshot_images = [self.create_snapshot_image(snapshot, plan) for plan in plans]

        for old_snapshot_image in old_snapshot_images:
            self.create_cached_snapshot_image(old_snapshot_image)

        get_current_datetime.return_value = self.mock_datetime

        gc.cache_snapshot(snapshot)
        # Ensure that the old snapshots now expire sometime in the future
        assert not db.session.query(CachedSnapshotImage.query.filter(
            CachedSnapshotImage.id.in_(old_snapshot_image_ids),
            sqlalchemy.or_(
                CachedSnapshotImage.expiration_date == None,  # NOQA
                CachedSnapshotImage.expiration_date <= self.mock_datetime
            )
        ).exists()).scalar()

    @mock.patch('changes.lib.snapshot_garbage_collection.get_current_datetime')
    def test_recache_existing_cached_snapshot(self, get_current_datetime):
        """
        In some cases we may want to re-cache an existing snapshot that
        already has an entry in the cache. This should be transparent.
        """
        project = self.create_project()
        plan = self.create_plan(project)
        snapshot = self.create_snapshot(project)
        snapshot_image = self.create_snapshot_image(snapshot, plan)

        get_current_datetime.return_value = self.mock_datetime

        self.create_cached_snapshot_image(snapshot_image,
            expiration_date=self.mock_datetime - datetime.timedelta(0, 1))
        gc.cache_snapshot(snapshot)

        # The old snapshot now has no expiration
        cached_snapshot_image = CachedSnapshotImage.query.get(snapshot_image.id)
        assert cached_snapshot_image is not None
        assert cached_snapshot_image.expiration_date is None

        # and is the only snapshot in existence
        assert CachedSnapshotImage.query.count() == 1