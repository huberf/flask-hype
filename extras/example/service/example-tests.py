import os
import hags.api as app_handle
import unittest
import tempfile
import json

class FlaskTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app_handle.app.test_client()

    def test_create_usr(self):
        credsplain = {'email_address': 'ex@ex.ex', 'password': '12345',}
        credentials = json.dumps(credsplain)
        print self.app.post('/users/', data=credentials, content_type='application/json', follow_redirects=True)
    
    '''
    def test_authenticate(self):
'''


if __name__ == '__main__':
    unittest.main()
