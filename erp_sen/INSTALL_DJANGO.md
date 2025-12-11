Instrucciones rápidas para instalar dependencias (macOS, zsh):

1) Crear y activar un virtualenv (recomendado):

```zsh
python3 -m venv .venv
source .venv/bin/activate
```

2) Actualizar pip y setuptools:

```zsh
pip install --upgrade pip setuptools
```

3) Instalar dependencias del proyecto:

```zsh
pip install -r requirements.txt
```

4) Comprobar instalación de Django:

```zsh
python -c "import django; print(django.get_version())"
```

Notas:
- Si usa PostgreSQL agregue `psycopg2-binary` a `requirements.txt`.
- Para entornos de producción use un gestor de procesos (gunicorn/uWSGI) y configure variables de entorno.
