# Bitácora — 2026-05-17 — Auditoría y correcciones: Architecture Enforcement Layer

## Contexto

Revisión crítica post-implementación del Architecture Enforcement Layer mediante dos sesiones de ultraplan. El objetivo fue determinar si el proyecto estaba listo para avanzar al diseño del Event Schema.

## Hallazgos de la auditoría

### Bug crítico resuelto — `_build_exchange` rompía el downloader

`src/data/ohlcv.py` tenía la siguiente llamada en `_build_exchange`:

```python
assert_allowed(Feature.FUTURES)  # semántica invertida
```

`assert_allowed(feature)` lanza `PhaseConstraintError` cuando el feature está **prohibido**. `Feature.FUTURES` está prohibido en Fase 1. Por lo tanto, `_build_exchange()` — y por extensión el CLI `aqcs-download` — lanzaba una excepción en cada invocación en Fase 1. El downloader OHLCV era completamente no funcional en producción.

Los tests no detectaban esto porque todos los tests de `TestBuildExchange` parcheaban `assert_allowed` con un mock:
```python
with patch("src.data.ohlcv.assert_allowed"), ...
```

**Corrección**: Se eliminó la llamada al guard y su import de `ohlcv.py`. La fábrica de exchange spot no debe gatear en `Feature.FUTURES`; ese guard pertenece a una ruta de ejecución de órdenes en futures, que no existe en Fase 1.

### Fragility en tests de arquitectura — paths relativos

`tests/architecture/test_dependency_boundaries.py` y `test_forbidden_imports.py` usaban:
```python
_SRC_FILES = sorted(Path("src").rglob("*.py"))
```

Si pytest se ejecutaba desde un directorio distinto al root del proyecto, `Path("src")` resolvía a 0 archivos — los tests pasaban vacuosamente sin verificar nada.

**Corrección**: Ambos archivos usan ahora `Path(__file__).resolve().parents[2] / "src"` — path absoluto independiente del CWD.

### Inaccuracies en documentación corregidas

1. `system-architecture-v1.md §6` afirmaba que ruff enforcea el boundary LLM/Quant. Es falso: lo hace `test_dependency_boundaries.py`. Corregido.
2. README decía "All 17 unit tests should pass" — número desactualizado después de agregar 100+ tests de arquitectura. Corregido.
3. `project-standards.md` tenía lenguaje ambiguo sobre `standards.md` ("maintained in parallel"). Corregido: `standards.md` está deprecado, `project-standards.md` es el canónico.

## Estado del CI

GitHub Actions (`.github/workflows/ci.yml`) está implementado y operacional. Ejecuta en cada push:
- `ruff check` + `black --check`
- `mypy src/`
- `pytest tests/ -v --cov=src`

El bitácora de 2026-05-16 listaba "CI/CD con GitHub Actions" como tarea futura de Fase 2. Esta tarea está completa.

## Veredicto de auditoría

**GO para Event Schema** — después de las correcciones aplicadas hoy.

El skeleton de Fase 1 es correcto y minimal:
- DAG de dependencias enforceado via AST estático
- LLM Oversight boundary enforceado y verificable
- Phase Guard funcional y con fail-closed en fases desconocidas
- ccxt aislado en `src/data/`
- Sin rutas de orden real
- Sin overengineering

## Próximos pasos

1. Event Schema institucional (diseño e implementación)
2. Verificar que el CI pasa en GitHub Actions en el próximo push

---

*Bitácora generada el 2026-05-17. AQCS v0.1.0.*
