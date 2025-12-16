from django.db import models

class ImportBatch(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    file_name = models.CharField(max_length=255)
    total_rows = models.IntegerField(default=0)
    success_rows = models.IntegerField(default=0)
    failed_rows = models.IntegerField(default=0)
    notes = models.TextField(blank=True)
    can_undo = models.BooleanField(default=True)
    undone_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Import {self.id} - {self.file_name}"


class GameResult(models.Model):
    result = models.IntegerField(help_text='Final number 0–27')
    timestamp = models.DateTimeField(null=True, blank=True)
    source_file = models.CharField(max_length=255, blank=True)
    winners_count = models.IntegerField(null=True, blank=True)
    prize_amount = models.BigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    import_batch = models.ForeignKey(ImportBatch, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='results')

    class Meta:
        ordering = ['-timestamp', '-id']

    def __str__(self):
        return f'{self.result} @ {self.timestamp or "no-time"}'

    @property
    def size_group(self):
        if 0 <= self.result <= 13:
            return 'Small'
        if 14 <= self.result <= 27:
            return 'Big'
        return 'Unknown'

    @property
    def parity_group(self):
        return 'Even' if self.result % 2 == 0 else 'Odd'

    @property
    def combo_group(self):
        if 0 <= self.result <= 13 and self.result % 2 == 1:
            return 'SO'
        if 0 <= self.result <= 13 and self.result % 2 == 0:
            return 'SE'
        if 14 <= self.result <= 27 and self.result % 2 == 1:
            return 'BO'
        if 14 <= self.result <= 27 and self.result % 2 == 0:
            return 'BE'
        return 'NA'
