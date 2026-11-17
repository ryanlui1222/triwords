from datetime import date
import importlib
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir=tempfile.TemporaryDirectory()
        os.environ.pop('TURSO_DATABASE_URL',None)
        os.environ['LOCAL_DB_PATH']=str(Path(cls.tempdir.name)/'test.db')
        os.environ['APP_TIMEZONE']='Asia/Hong_Kong'
        os.environ['APP_PASSWORD']='strong-test-password-012345'
        os.environ['SESSION_SECRET']='long-test-session-secret-string-value-at-least-32'
        import db
        importlib.reload(db)
        import seed_demo
        importlib.reload(seed_demo)
        seed_demo.seed('2026-11-18')
        import app
        importlib.reload(app)
        cls.db=db
        cls.client=TestClient(app.app)

    @classmethod
    def tearDownClass(cls):
        cls.tempdir.cleanup()

    def login(self):
        result=self.client.post('/api/login',json={'password':'strong-test-password-012345'})
        self.assertEqual(result.status_code,200,result.text)

    def test_public_is_login_protected(self):
        anonymous=TestClient(__import__('app').app)
        self.assertEqual(anonymous.get('/api/library').status_code,401)
        self.assertEqual(anonymous.post('/api/login',json={'password':'wrong'}).status_code,401)
        self.assertTrue(anonymous.get('/').text.find('三語日課')>0)

    def test_lessons_library_review_bookmark(self):
        self.login()
        words=self.client.get('/api/lesson?date=2026-11-18').json()['words']
        self.assertEqual(len(words),30)
        self.assertEqual({lang:sum(w['language']==lang for w in words) for lang in ('en','ja','es')},{'en':10,'ja':10,'es':10})
        self.assertEqual(len(self.client.get('/api/library?lang=ja').json()['words']),10)
        self.assertEqual(self.client.get('/static/app.js').status_code,200)
        self.assertEqual(self.client.get('/static/manifest.webmanifest').status_code,200)
        word=words[0]
        data={'word_id':word['id'],'rating':'good','request_id':'unique-first-test-event'}
        first=self.client.post('/api/review',json=data)
        self.assertEqual(first.status_code,200,first.text)
        self.assertFalse(first.json()['duplicate'])
        again=self.client.post('/api/review',json=data)
        self.assertTrue(again.json()['duplicate'])
        self.assertEqual(self.client.post(f"/api/bookmark/{word['id']}",json={'enabled':True}).status_code,200)
        only=self.client.get('/api/library?bookmarked=true').json()['words']
        self.assertEqual(len(only),1)
        self.assertEqual(only[0]['term'],word['term'])
        self.assertEqual(len(self.client.get('/api/library?limit=3&offset=2').json()['words']),3)
        self.assertEqual(self.client.get('/api/library?limit=300').status_code,400)

    def test_security_origin_and_input(self):
        self.login()
        self.assertEqual(self.client.post('/api/review',headers={'Origin':'https://evil.example'},json={'word_id':'x','rating':'good','request_id':'a'}).status_code,403)
        self.assertEqual(self.client.get('/api/lesson?date=bad-date').status_code,400)
        self.assertEqual(self.client.post('/api/review',json={'word_id':'unknown','rating':'good','request_id':'different-event'}).status_code,404)

    def test_generator_validation(self):
        from generate_daily import validate
        valid=[{'term':f'example-{i}','reading':'reading','part_of_speech':'noun','meaning_zh':'含義','example':'Example sentence.','example_zh':'例句。','level':'C1','topic':'demo'} for i in range(15)]
        self.assertEqual(len(validate(valid,'en',['example-0'])),10)
        with self.assertRaises(RuntimeError):validate(valid[:7],'en',[])

    def test_schedule(self):
        reps,interval,ease,due=self.db.calculate_next(None,'good','2026-11-18')
        self.assertEqual((reps,interval,due),(1,1,'2026-11-19'))
        self.assertEqual(self.db.calculate_next((2,6,2.5),'again','2026-11-18')[1],1)

if __name__=='__main__': unittest.main()
