from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('games', '0020_new_number_series')]
    operations = [migrations.AddField(
        model_name='windowalertstate', name='drought_destinations',
        field=models.ManyToManyField(blank=True, related_name='window_drought_states', to='games.alertdestination'),
    )]
