# Test settings: AWX unit-test settings, but against a real PostgreSQL.
import os

from awx.main.tests.settings_for_test import *  # noqa

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('PGDATABASE', 'awx'),
        'USER': 'awx',
        'PASSWORD': 'awx',
        'HOST': '127.0.0.1',
        'PORT': os.environ.get('PGPORT', '55432'),
    }
}
