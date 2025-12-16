
import os
import django
from django.utils.timezone import make_aware
from datetime import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lucky28_backend.settings')
django.setup()

from gameapp.models import GameResult

def check_count():
    date_str = '2025-12-14'
    start = make_aware(datetime.strptime(date_str, '%Y-%m-%d'))
    end = make_aware(datetime.strptime(date_str + ' 23:59:59', '%Y-%m-%d %H:%M:%S'))
    
    from django.conf import settings
    print(f"DB Path: {settings.DATABASES['default']['NAME']}")
    
    count = GameResult.objects.filter(timestamp__range=(start, end)).count()
    print(f"Total objects for {date_str}: {count}")
    
    # Check sample times
    all_objs = GameResult.objects.filter(timestamp__range=(start, end))
    if count > 0:
        print(f"First 5: {all_objs.order_by('timestamp')[:5]}")
        print(f"Last 5: {all_objs.order_by('timestamp').reverse()[:5]}")
    else:
        # Check if they are on another day?
        total = GameResult.objects.count()
        print(f"Total objects in ENTIRE DB: {total}")
        if total > 0:
            print(f"First ANY: {GameResult.objects.first().timestamp}")


if __name__ == '__main__':
    check_count()
