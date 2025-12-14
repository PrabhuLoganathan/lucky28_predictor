from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import render, redirect
from django.utils import timezone
from datetime import timedelta
import csv, io

from .models import GameResult, ImportBatch
from .forms import CSVImportForm


@admin.register(GameResult)
class GameResultAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'result',
        'size_group',
        'parity_group',
        'combo_group',
        'timestamp',
        'timestamp',
        'winners_count',
        'prize_amount',
        'source_file',
        'created_at',
    )
    # Only actual DB fields in list_filter
    list_filter = ('result', 'source_file')
    search_fields = ('source_file',)
    change_list_template = 'admin/gameapp/gameresult/change_list.html'

    def get_urls(self):
        urls = super().get_urls()
        extra = [
            path(
                'import-csv/',
                self.admin_site.admin_view(self.import_csv),
                name='gameapp_gameresult_import_csv',
            ),
        ]
        return extra + urls

    def import_csv(self, request):
        if request.method == 'POST':
            form = CSVImportForm(request.POST, request.FILES)
            if form.is_valid():
                csv_file = form.cleaned_data['csv_file']
                try:
                    decoded = csv_file.read().decode('utf-8')
                except UnicodeDecodeError:
                    decoded = csv_file.read().decode('latin1')

                reader = csv.reader(io.StringIO(decoded))
                header = next(reader, None)
                if not header or header[0].strip().lower() != 'result':
                    self.message_user(
                        request,
                        'CSV must have a first column named "result".',
                        level=messages.ERROR,
                    )
                    return redirect('admin:gameapp_gameresult_changelist')

                batch = ImportBatch.objects.create(file_name=csv_file.name)
                base_ts = timezone.now()

                total = success = failed = 0
                for offset, row in enumerate(reader):
                    if not row or not row[0].strip():
                        continue
                    total += 1
                    try:
                        val = int(row[0])
                        if not (0 <= val <= 27):
                            raise ValueError('Result must be 0–27')
                        
                        # Optional fields
                        w_count = None
                        p_amount = None
                        
                        # Try to find specific columns if header exists and has enough columns
                        # This simple logic assumes the structure: Result, [Timestamp/Ignored], Winners, Prizes
                        # Or just tries to parse specific indices if row is long enough
                        # Let's try to be smart about column indices if header is present
                        
                        # Basic fallback: 
                        # col 0: Result
                        # col 1: Winners (optional)
                        # col 2: Prizes (optional)
                        
                        if len(row) > 1 and row[1].strip().isdigit():
                            w_count = int(row[1])
                        
                        if len(row) > 2:
                            # Cleanup currency strings like "22,551,671"
                            p_str = row[2].replace(',', '').strip()
                            if p_str.isdigit():
                                p_amount = int(p_str)

                        ts = base_ts - timedelta(minutes=offset)
                        GameResult.objects.create(
                            result=val,
                            timestamp=ts,
                            source_file=csv_file.name,
                            import_batch=batch,
                            winners_count=w_count,
                            prize_amount=p_amount,
                        )
                        success += 1
                    except Exception as e:
                        # print(f"Row failed: {row} - {e}")
                        failed += 1

                batch.total_rows = total
                batch.success_rows = success
                batch.failed_rows = failed
                batch.save()

                self.message_user(
                    request,
                    f'Imported {success}/{total} rows.',
                    level=messages.SUCCESS if failed == 0 else messages.WARNING,
                )
                return redirect('admin:gameapp_gameresult_changelist')
        else:
            form = CSVImportForm()

        ctx = {
            'title': 'Import Game Results from CSV',
            'form': form,
            'opts': self.model._meta,
            'app_label': self.model._meta.app_label,
        }
        return render(request, 'admin/gameapp/gameresult/import_csv.html', ctx)


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'file_name',
        'created_at',
        'total_rows',
        'success_rows',
        'failed_rows',
    )
    readonly_fields = ('created_at',)
