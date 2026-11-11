#!/usr/bin/env python3
"""
Face Registration Tool

Unified registration system using the same DeepFace-based
FaceRecognitionService used by the main application.
"""

import os
import sys
import getpass
from pathlib import Path
from typing import Optional, List

import cv2
import numpy as np

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings, settings_dict
from app.security.auth import auth_manager, validate_password_strength
from app.database.db import db_manager
from app.services.face_recognition import (
    FaceRecognitionService, dedupe_embeddings, dedupe_image_bytes,
)


def authenticate_cli(max_attempts: int = 3) -> bool:
    """Authenticate admin user via CLI."""
    # Check if blocked
    blocked, remaining = auth_manager.is_blocked()
    if blocked:
        print(f'⚠️  Sistema bloqueado. Aguarde {remaining // 60} minutos e {remaining % 60} segundos.')
        return False

    print('🔐 Autenticação requerida para cadastrar pessoas.')
    print()

    for attempt in range(max_attempts):
        try:
            password = getpass.getpass(f'   Senha admin (tentativa {attempt + 1}/{max_attempts}): ')
        except (KeyboardInterrupt, EOFError):
            print('\n   Cancelado.')
            return False
        
        if auth_manager.verify_password(password):
            print('   ✅ Autenticado com sucesso!')
            return True
        else:
            print('   ❌ Senha incorreta.')

    blocked, remaining = auth_manager.is_blocked()
    if blocked:
        print(f'\n⚠️  Tentativas esgotadas. Sistema bloqueado por {remaining // 60} minutos.')
    return False


def process_images(image_paths: List[str], face_service: FaceRecognitionService) -> Optional[np.ndarray]:
    """
    Process multiple images and return averaged embedding.
    
    Uses the same DeepFace-based FaceRecognitionService as the main app,
    ensuring consistency between registration and recognition.
    """
    embeddings = []

    # O mesmo arquivo informado duas vezes (ou cópias idênticas com outro
    # nome) dava um par com distância 0 e puxava a média para aquela foto.
    lidos: List[tuple] = []
    for img_path in image_paths:
        try:
            lidos.append((img_path, Path(img_path).read_bytes()))
        except OSError:
            lidos.append((img_path, None))
    unicos, repetidas = dedupe_image_bytes([c for _, c in lidos if c is not None])
    # dedupe_image_bytes devolve os mesmos objetos bytes, na ordem: o que não
    # está na frente da fila de únicos é repetição de um anterior.
    restantes = list(unicos)
    selecionados = []
    for img_path, conteudo in lidos:
        if conteudo is not None:
            if restantes and restantes[0] is conteudo:
                restantes.pop(0)
            else:
                print(f'   ↷ {img_path}: foto repetida, ignorada')
                continue
        selecionados.append((img_path, conteudo))

    print(f'\n📸 Processando {len(selecionados)} imagem(ns)...')

    for img_path, conteudo in selecionados:
        print(f'   → {img_path}')

        # Load image (imdecode dos bytes já lidos; cv2.imread falha com
        # caminho acentuado no Windows)
        img = None
        if conteudo is not None:
            img = cv2.imdecode(np.frombuffer(conteudo, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print(f'      ⚠️  Não foi possível carregar imagem')
            continue
        
        # Use FaceRecognitionService to extract embedding
        # This ensures consistency with the recognition pipeline
        embedding = face_service.register_face(img)
        
        if embedding is not None:
            embeddings.append(embedding)
            print(f'      ✅ Embedding extraído (dim={embedding.shape[0]})')
        else:
            print(f'      ⚠️  Nenhum rosto válido detectado')
    
    if not embeddings:
        print('\n❌ Erro: Nenhum embedding facial válido encontrado.')
        return None

    # Quase-duplicatas: a mesma foto reencodada, frames seguidos de vídeo.
    embeddings, quase_iguais = dedupe_embeddings(embeddings)
    if repetidas or quase_iguais:
        print(f'   ↷ {repetidas + quase_iguais} foto(s) repetida(s) descartada(s)')

    # Average embeddings from all valid images
    if len(embeddings) == 1:
        avg_embedding = embeddings[0]
    else:
        avg_embedding = np.mean(embeddings, axis=0)
        # Re-normalize after averaging
        norm = np.linalg.norm(avg_embedding)
        if norm > 0:
            avg_embedding = avg_embedding / norm
    
    print(f'\n📊 Média de {len(embeddings)} embedding(s) gerada')
    return avg_embedding


def register_person(name: str, email: Optional[str], image_paths: List[str], face_service: FaceRecognitionService) -> bool:
    """Register a person in the database with their facial embedding."""
    
    # Check if user already exists
    existing = db_manager.get_user_by_name(name)
    if existing:
        print(f'⚠️  Erro: Pessoa "{name}" já está cadastrada (ID: {existing.id})')
        return False
    
    # Process images and get embedding
    embedding = process_images(image_paths, face_service)
    if embedding is None:
        return False

    # O mesmo rosto sob outro nome: o log de acesso registraria a pessoa
    # errada. Recusa sempre. Carrega os rostos do banco agora - o serviço do
    # CLI não os tem em memória, e alguém pode ter cadastrado pela API.
    face_service.load_known_faces(db_manager.get_all_embeddings_data())
    conflito = face_service.find_identity_conflict(embedding)
    if conflito is not None:
        conflito_id, conflito_nome, distancia = conflito
        print(f'\n❌ Cadastro recusado: este rosto já está cadastrado como '
              f'"{conflito_nome}" (ID: {conflito_id}, distância {distancia:.3f}).')
        return False

    try:
        # Create user in database
        print(f'\n💾 Salvando no banco de dados...')
        user = db_manager.create_user(name=name, email=email, role="user")
        
        # Add embedding
        # O backend que gerou o vetor de fato (ver load_known_faces).
        db_manager.add_embedding(
            user_id=user.id,
            embedding_data=embedding.tolist(),
            model_used=face_service.embedding_backend,
            is_primary=True
        )
        
        # Log the action
        db_manager.log_access(
            user_id=user.id,
            action="register",
            status="success",
            ip_address="cli",
            details={"image_count": len(image_paths)}
        )
        
        print(f'\n✅ Pessoa "{name}" cadastrada com sucesso!')
        print(f'   ID: {user.id}')
        print(f'   Modelo: {settings.face_model}')
        print(f'   Dimensão do embedding: {embedding.shape[0]}')
        return True
        
    except Exception as e:
        print(f'\n❌ Erro ao salvar no banco de dados: {e}')
        return False


def list_registered_users():
    """List all registered users."""
    users = db_manager.get_all_users(active_only=False)
    
    if not users:
        print('\n   Nenhum usuário cadastrado.')
        return
    
    print(f'\n📋 {len(users)} usuário(s) cadastrado(s):')
    print()
    print(f'   {"ID":<5} {"Nome":<30} {"Email":<25} {"Status"}')
    print('   ' + '-' * 70)
    
    for user in users:
        status = "🟢 Ativo" if user.is_active else "🔴 Inativo"
        email = user.email or "-"
        print(f'   {user.id:<5} {user.name[:28]:<30} {email[:23]:<25} {status}')


def main():
    print()
    print('=' * 60)
    print('  🔐 CADASTRO DE PESSOAS - RECONHECIMENTO FACIAL PRO 3.0')
    print('=' * 60)
    print()
    
    # Check face service availability
    face_service = FaceRecognitionService(settings_dict)
    if not face_service.initialize():
        print('❌ Erro: Não foi possível inicializar o serviço de reconhecimento facial.')
        return
    
    # Show which backend is actually in use (not just which is installed)
    backend_info = face_service.get_backend_info()
    if backend_info["degraded"]:
        print(f'⚠️  RECONHECIMENTO DEGRADADO: embeddings via '
              f'\'{backend_info["embedding_backend"]}\' — não identifica pessoa de verdade.')
    else:
        print(f'✅ Serviço de reconhecimento inicializado '
              f'(detecção: {backend_info["detection_backend"]}, '
              f'embedding: {backend_info["embedding_backend"]})')
    
    # Authenticate
    if not authenticate_cli():
        return
    
    # Menu
    while True:
        print()
        print('Opções:')
        print('   [1] Cadastrar nova pessoa')
        print('   [2] Listar pessoas cadastradas')
        print('   [3] Sair')
        print()
        
        try:
            choice = input('   Escolha: ').strip()
        except (KeyboardInterrupt, EOFError):
            print('\n\n👋 Saindo...')
            break
        
        if choice == '1':
            # Register new person
            print()
            print('--- Cadastro de Nova Pessoa ---')
            
            name = input('\n   Nome da pessoa: ').strip()
            if not name:
                print('   ⚠️  Nome não pode estar vazio.')
                continue
            
            email = input('   Email (opcional): ').strip() or None
            
            print('\n   Caminhos das imagens (separados por vírgula):')
            print('   Exemplo: fotos/joao1.jpg, fotos/joao2.jpg')
            paths_input = input('   ').strip()
            
            if not paths_input:
                print('   ⚠️  Nenhuma imagem fornecida.')
                continue
            
            # Validate paths
            image_paths = [p.strip() for p in paths_input.split(',')]
            valid_paths = [p for p in image_paths if os.path.exists(p)]
            
            if not valid_paths:
                print('   ❌ Nenhum arquivo de imagem encontrado.')
                continue
            
            # Register
            register_person(name, email, valid_paths, face_service)
            
        elif choice == '2':
            # List users
            list_registered_users()
            
        elif choice == '3':
            print('\n👋 Saindo...')
            break
            
        else:
            print('   ⚠️  Opção inválida.')


if __name__ == '__main__':
    main()