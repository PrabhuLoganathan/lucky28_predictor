from django.shortcuts import render
from datetime import datetime, date, time
from django.utils import timezone
from .models import GameResult

def homepage(request):
    date_str = request.GET.get('date')
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = timezone.now().date()
    else:
        selected_date = timezone.now().date()

    # Filter by range to ensure robust datetime filtering
    start_of_day = datetime.combine(selected_date, time.min)
    end_of_day = datetime.combine(selected_date, time.max)
    
    # Make them timezone aware if using TZ
    if timezone.is_aware(timezone.now()):
        start_of_day = timezone.make_aware(start_of_day)
        end_of_day = timezone.make_aware(end_of_day)

    results = GameResult.objects.filter(
        timestamp__range=(start_of_day, end_of_day)
    ).order_by('-timestamp')

    context = {
        'results': results,
        'selected_date': selected_date.strftime('%Y-%m-%d'),
        'today': timezone.now().date().strftime('%Y-%m-%d'),
    }
    return render(request, 'gameapp/homepage.html', context)
