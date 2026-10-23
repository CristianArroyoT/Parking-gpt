"""Los correos se guardan y se comparan en forma canonica (T-99).

POR QUE: un correo **no distingue** mayusculas de minusculas, pero el
codigo comparaba el texto tal como se escribia. Medido el 2026-10-23
contra la API real en marcha: un usuario creado como
``Gestor.Mixto@solidapp.es`` se logueaba con ese correo exacto (200) y
**no** con ``gestor.mixto@solidapp.es`` (401).

Esta migracion hace dos cosas:

1. **Canoniza** los correos que ya hay (``lower(trim(email))``). Si
   hubiera dos cuentas que solo se diferenciaran en como estan escritas,
   la actualizacion **falla** (el UNIQUE de la columna lo prohibe): es
   mejor que el despliegue se pare y lo diga a que dejar dos cuentas
   indistinguibles.

2. **Anade un indice unico sobre ``lower(email)``**. El UNIQUE de la
   columna es sensible a mayusculas, asi que sin este indice se podrian
   crear dos cuentas que solo se diferencien en como estan escritas. Y el
   login (que ya compara en forma canonica) las confundiria.

El ``downgrade`` quita el indice; los correos **se quedan canonicos** (la
forma original no se puede recuperar, y no importa: la canonica es la
correcta).

Revisa: 0014_indices_y_uniques
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_email_canonico"
down_revision: str | None = "0014_indices_y_uniques"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Canonizar los correos existentes.
    op.execute(sa.text("UPDATE users SET email = lower(trim(email))"))
    # 2) Unicidad sin distinguir mayusculas.
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_users_email_lower", table_name="users")
    # Los correos quedan canonicos: no se puede recuperar la forma
    # original, y no hace falta (la canonica es la correcta).
