import os
import sys
import getpass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import load_config
from app.security.auth import auth_manager
from app.database.db import db_manager


def authenticate(max_attempts: int = 3) -> bool:
    """Authenticate admin user via CLI using the unified auth system."""
    # Check if blocked
    blocked, remaining = auth_manager.is_blocked()
    if blocked:
        print(f'Sistema bloqueado. Aguarde {remaining // 60} minutos e {remaining % 60} segundos.')
        return False

    for attempt in range(max_attempts):
        try:
            password = getpass.getpass(f'Senha admin (tentativa {attempt + 1}/{max_attempts}): ')
        except (KeyboardInterrupt, EOFError):
            print('\nCancelado.')
            return False
            
        if auth_manager.verify_password(password):
            return True
        else:
            print('Senha incorreta.')

    # Check block status again to show correct message
    blocked, remaining = auth_manager.is_blocked()
    if blocked:
        print(f'Tentativas esgotadas. Bloqueado por {remaining // 60} minutos.')
    return False


def main():
    print('=' * 50)
    print('  REMOÇÃO DE PESSOAS - RECONHECIMENTO FACIAL')
    print('=' * 50)
    print()

    config = load_config()

    print('Autenticação requerida para remover pessoas.')
    if not authenticate():
        return

    db_manager.log_access(user_id=None, action="admin_remove_attempt", status="success", ip_address="cli")



    # Use db_manager to list users
    registered_users = db_manager.get_all_users(active_only=False)

    if not registered_users:
        print('Nenhuma pessoa cadastrada.')
        return

    print('\nPessoas cadastradas:')
    for i, user in enumerate(registered_users, 1):
        status = "Ativo" if user.is_active else "Inativo"
        print(f'  {i}. {user.name} ({status})')

    print('\nDigite o número da pessoa a remover (ou 0 para cancelar): ', end='')
    try:
        choice = int(input().strip())
    except ValueError:
        print('Entrada inválida.')
        return

    if choice == 0:
        print('Operação cancelada.')
        return

    if choice < 1 or choice > len(registered_users):
        print('Número inválido.')
        return

    user_to_remove = registered_users[choice - 1]
    print(f'\nRemover "{user_to_remove.name}" e todos os seus dados biométricos? (s/n): ', end='')
    confirm = input().strip().lower()

    if confirm != 's':
        print('Operação cancelada.')
        return

    if db_manager.delete_user(user_to_remove.id):
        # The new db_manager handles AccessLog and Embeddings cascade
        print(f'Pessoa "{user_to_remove.name}" removida com sucesso!')
    else:
        print('Erro ao remover pessoa.')


if __name__ == '__main__':
    main()

