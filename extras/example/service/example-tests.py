import os
import hags.api as flaskr
import unittest
import tempfile
import json

class FlaskrTestCase(unittest.TestCase):
    def setUp(self):
        self.app = flaskr.app.test_client()

    def test_create_usr(self):
        credsplain = {'email_address': 'ex@ex.ex', 'password': '12345',}
        credentials = json.dumps(credsplain)
        print self.app.post('/users/', data=credentials, content_type='application/json', follow_redirects=True)

'''
    def test_me(self):
        print self.app.get('/users/me')
'''

if __name__ == '__main__':
    unittest.main()
