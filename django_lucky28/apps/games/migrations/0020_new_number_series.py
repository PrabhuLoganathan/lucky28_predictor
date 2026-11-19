from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('games', '0019_category_direct_routing')]
    operations = [migrations.AlterField(
        model_name='alertrule', name='series',
        field=models.CharField(choices=[(s, s.title()) for s in
            ('size', 'parity', 'color', 'number', 'tip', 'new_repeat')], max_length=16),
    )]
