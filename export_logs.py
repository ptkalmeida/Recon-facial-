import os
import sys
import csv
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.database.db import db_manager, load_config


def export_logs(output_file: str, start_date: str = None, end_date: str = None):
    config = load_config()
    
    # Use modern db_manager
    # Convert dates to datetime if provided
    start_dt = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") if end_date else None
    # Add one day to end_dt to include the full end day
    if end_dt:
        end_dt = end_dt + timedelta(days=1)

    records = db_manager.get_presence_records(date=start_date if start_date == end_date else None)
    # If a range was requested but get_presence_records only takes one date, 
    # we might need to filter manually or update db_manager.
    # For now, let's use the existing db_manager.get_presence_records and filter if needed.
    
    if start_date and end_date and start_date != end_date:
        # Range filtering
        records = [r for r in records if start_date <= r.created_at.strftime("%Y-%m-%d") <= end_date]

    if not records:
        print('Nenhum registro encontrado.')
        return False

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Nome', 'Data', 'Hora', 'Tipo'])

        for record in records:
            writer.writerow([
                record.user.name if record.user else "Unknown",
                record.created_at.strftime('%Y-%m-%d'),
                record.created_at.strftime('%H:%M:%S'),
                record.status
            ])

    print(f'Exportados {len(records)} registros para: {output_file}')
    return True



def main():
    print('=' * 50)
    print('  EXPORTAÇÃO DE LOGS - RECONHECIMENTO FACIAL')
    print('=' * 50)
    print()

    if not os.path.exists(db_manager.db_path):
        print(f'Erro: Banco de dados não encontrado em {db_manager.db_path}.')
        return


    print('Filtrar por período (opcional):')
    print('  1. Todos os registros')
    print('  2. Hoje')
    print('  3. Últimos 7 dias')
    print('  4. Últimos 30 dias')
    print('  5. Personalizado')
    print()

    choice = input('Escolha uma opção (1-5): ').strip()

    start_date = None
    end_date = None

    today = datetime.now().strftime('%Y-%m-%d')

    if choice == '2':
        start_date = today
        end_date = today
    elif choice == '3':
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        end_date = today
    elif choice == '4':
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        end_date = today
    elif choice == '5':
        print('\nData inicial (YYYY-MM-DD): ', end='')
        start_date = input().strip()
        print('Data final (YYYY-MM-DD): ', end='')
        end_date = input().strip()

    default_filename = f'logs_presenca_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    print(f'\nNome do arquivo (padrão: {default_filename}): ', end='')
    filename = input().strip()

    output_file = filename if filename else default_filename

    export_logs(output_file, start_date, end_date)


if __name__ == '__main__':
    main()