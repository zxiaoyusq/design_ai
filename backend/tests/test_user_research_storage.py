"""PPT 工作台离线夹具，验证来源边界、出现关系和持久化安全。"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from app.services.user_research.storage import ResearchStore


class ResearchStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.images = self.base / 'images'
        self.images.mkdir()
        self.picture = self.images / 'test.png'
        self.picture.write_bytes(b'synthetic-image')
        self.seed = self.base / 'seed.json'
        self.original = {'users': [{'id': '75', 'name': 'synthetic_fixture', 'profile': {'age': 16},
            'ppt_supplement': {'source_file': '/old/private/report.pptx', 'source_sha256': 'abc'},
            'aesthetic_research': [
                {'id': 'old', 'question': '旧分析', 'ai_analysis': '不能当PPT原话'},
                {'id': 'q1', 'source_type': 'ppt_supplement', 'question': '选择', 'ai_analysis': '喜欢A、不喜欢A',
                 'ref_pic_links': [
                     {'code': 'A', 'image_ids': ['img'], 'emotion_tag': 'ENJOY'},
                     {'code': 'A', 'image_ids': ['img'], 'emotion_tag': 'DISLIKE'},
                     {'code': 'B', 'image_ids': [], 'emotion_tag': 'ENJOY', 'status': 'missing_source_image'}]}],
            'ppt_images': [{'image_id': 'img', 'ref_pic_code': 'A', 'local_path': 'test.png',
                            'source_question_id': 'q1', 'emotion_tag': 'ENJOY'}],
            'image_preferences': [{'image_id': 'legacy', 'emotion_tag': 'ENJOY'}]}]}
        self.seed.write_text(json.dumps(self.original))
        self.store = ResearchStore(root=self.base/'runs', seed_file=self.seed, image_root=self.images)

    def test_ppt_only_duplicate_stances_and_missing_choices(self):
        user = self.store.get_user('75')
        self.assertEqual([r['id'] for r in user['records']], ['q1'])
        self.assertEqual(user['records'][0]['answer'], '喜欢A、不喜欢A')
        self.assertEqual(len(user['records'][0]['imageIds']), 3)
        self.assertEqual((user['enjoyCount'],user['dislikeCount'],user['missingImageCount']), (2,1,1))
        self.assertEqual(user['sourceFile'], 'report.pptx')
        self.assertNotIn('legacy', [x['id'] for x in user['images']])
        self.assertEqual(self.store.asset_path('75','img'), self.picture)
        self.assertEqual(user['images'][0]['url'], '/api/v1/user-research/assets/75/img')
        user['profile']['age']=99
        self.assertEqual(self.store.get_user('75')['profile']['age'], 16)
        self.assertEqual(json.loads(self.seed.read_text()), self.original)

    def test_cache_refresh_and_reference_not_filename_guess(self):
        self.store.list_users()
        changed=copy.deepcopy(self.original)
        changed['users'][0]['ppt_images'][0].pop('emotion_tag')
        changed['users'][0]['ppt_images'][0]['ref_pic_code']='DISLIKE-NAME'
        changed['users'][0]['aesthetic_research'][1]['ref_pic_links']=[]
        self.seed.write_text(json.dumps(changed))
        user=self.store.get_user('75')
        self.assertEqual(user['images'][0]['emotion'], 'REFERENCE')

    def test_traversal_symlinks_and_unknown_assets(self):
        for uid in ('../75', '/etc/passwd'):
            with self.assertRaises(ValueError):self.store.get_user(uid)
        with self.assertRaises(FileNotFoundError):self.store.get_user('999')
        with self.assertRaises(FileNotFoundError):self.store.asset_path('75','unknown')
        self.picture.unlink()
        self.picture.symlink_to(self.seed)
        user=self.store.get_user('75')
        self.assertIsNone(user['images'][0]['url'])
        with self.assertRaises(FileNotFoundError):self.store.asset_path('75','img')

    def test_historical_ready_and_file_recovery_without_seed_change(self):
        self.picture.unlink()
        before = self.store.get_user('75')
        self.assertEqual(before['status'], 'ready')
        self.assertIsNone(before['images'][0]['url'])
        seed_mtime = self.seed.stat().st_mtime_ns
        self.picture.write_bytes(b'recovered-original-bytes')
        after = self.store.get_user('75')
        self.assertEqual(after['status'], 'ready')
        self.assertIsNotNone(after['images'][0]['url'])
        self.assertEqual(self.seed.stat().st_mtime_ns, seed_mtime)
        self.assertEqual(self.store.asset_path('75', 'img'), self.picture)

    def test_readable_section_priority_and_fallback(self):
        for fields, expected in [({'scenario_type': '当前手机', 'question_type': '品牌'}, '当前手机'),
                                 ({'scenario_type': ' ', 'question_type': '品牌'}, '品牌'),
                                 ({}, 'aesthetic_research')]:
            value = copy.deepcopy(self.original)
            value['users'][0]['aesthetic_research'][1].update(fields)
            self.seed.write_text(json.dumps(value))
            self.assertEqual(self.store.get_user('75')['records'][0]['section'], expected)

    def test_imported_removed_and_restored_assets_are_reflected(self):
        uid = 'import_' + 'b' * 32
        value = self.store.get_user('75')
        value['id'] = uid
        self.store.save_user(value, {x['id']: self.picture for x in value['images'] if x['url']})
        run_file = self.base / 'runs' / ('b' * 32) / 'user.json'
        frozen = run_file.read_bytes()
        self.picture.unlink()
        removed = self.store.get_user(uid)
        self.assertEqual(removed['missingImageCount'], 3)
        self.assertIsNone(removed['images'][0]['url'])
        self.assertEqual(next(u for u in self.store.list_users() if u['id'] == uid)['missingImageCount'], 3)
        with self.assertRaises(FileNotFoundError):
            self.store.asset_path(uid, 'img')
        self.picture.symlink_to(self.seed)
        self.assertIsNone(self.store.get_user(uid)['images'][0]['url'])
        self.picture.unlink()
        self.picture.write_bytes(b'restored')
        self.assertEqual(self.store.get_user(uid)['missingImageCount'], 1)
        self.assertEqual(run_file.read_bytes(), frozen)

    def test_linked_copy_requires_explicit_evidence_and_keeps_original(self):
        data = copy.deepcopy(self.original)
        user = data['users'][0]
        user['aesthetic_research'][1]['ref_pic_links'] = []
        original = user['ppt_images'][0]
        original.update(source_file='report.pptx', source_slide=3, sha256='original-sha')
        backup = self.images / 'backup.png'
        backup.write_bytes(b'original-survey-copy')
        (self.images / 'images.json').write_text(json.dumps({'images': [dict(
            id='survey-img', local_path='backup.png', sha256=hashlib.sha256(backup.read_bytes()).hexdigest())]}))
        link = dict(image_id='img', local_path='test.png', source_file='report.pptx',
                    source_slide=3, source_question_id='q1', evidence_scope='exact')
        preference = dict(image_id='survey-img', ref_pic_code='A', emotion_tag='ENJOY',
                          local_path='backup.png', ppt_evidence=[link])
        user['image_preferences'] = [preference]
        self.picture.unlink()
        for field, wrong in [('source_slide', 9), ('source_question_id', 'other'), ('image_id', 'unknown')]:
            invalid = copy.deepcopy(data)
            invalid['users'][0]['image_preferences'][0]['ppt_evidence'][0][field] = wrong
            self.seed.write_text(json.dumps(invalid))
            self.assertIsNone(self.store.get_user('75')['images'][0]['url'])
        self.seed.write_text(json.dumps(data))
        frozen = self.seed.read_bytes()
        detail = self.store.get_user('75')
        image = detail['images'][0]
        self.assertEqual(image['status'], 'linked_source_copy')
        self.assertEqual(image['recovery']['originalSha256'], 'original-sha')
        self.assertEqual(self.store.asset_path('75', 'img'), backup)
        self.assertEqual(detail['missingImageCount'], 0)
        backup.write_bytes(b'changed-image')
        self.assertIsNone(self.store.get_user('75')['images'][0]['url'])
        restarted = ResearchStore(root=self.base/'runs', seed_file=self.seed, image_root=self.images)
        self.assertIsNone(restarted.get_user('75')['images'][0]['url'])
        self.picture.write_bytes(b'recovered-original')
        restored = self.store.get_user('75')['images'][0]
        self.assertNotIn('recovery', restored)
        self.assertEqual(self.store.asset_path('75', 'img'), self.picture)
        self.assertEqual(self.seed.read_bytes(), frozen)

    def test_new_result_requires_confirmation_and_survives_restart(self):
        run_id='a'*32
        value=self.store.get_user('75')
        value['id']='import_'+run_id
        value['status']='ready'
        asset_map={x['id']:self.picture for x in value['images'] if x['url']}
        self.store.save_user(value,asset_map)
        saved=self.store.get_user(value['id'])
        self.assertEqual(saved['status'],'needs_review')
        saved['status']='ready'
        self.store.save_user(saved,asset_map)
        self.store.save_task({'id':run_id,'status':'completed'})
        restarted=ResearchStore(root=self.base/'runs',seed_file=self.seed,image_root=self.images)
        self.assertEqual(restarted.get_user(value['id'])['status'],'ready')
        self.assertEqual(len(restarted.list_users()),2)
        self.assertEqual(restarted.asset_path(value['id'],'img'),self.picture)
        self.assertEqual(restarted.list_tasks(),[{'id':run_id,'status':'completed'}])
        with self.assertRaises(ValueError):self.store.save_user(saved,{'img':self.seed})
        with self.assertRaises(ValueError):self.store.save_user(self.store.get_user('75'),{})
        with self.assertRaises(ValueError):self.store.get_task('../x')


if __name__=='__main__':
    unittest.main()
