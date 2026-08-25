from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.step_model import Macro, SalidaConfig, Selector, Step, StepType

from .inspector import CapturaSelector, Inspector
from .record_dialog import RecordDialog


COLS = ["#", "Tipo", "Selector", "Valor / Título", "Espera (s)", "Timeout (s)", "Opc.", "Descripción"]


class _RangeRunThread(QThread):
    """Ejecuta un sub-rango de la macro (ReplayRunner con start/stop)."""

    finished_summary = pyqtSignal(object)  # ReplaySummary
    error = pyqtSignal(str)

    def __init__(self, runner):
        super().__init__()
        self.runner = runner

    def run(self):
        try:
            summary = self.runner.run()
            self.finished_summary.emit(summary)
        except Exception as exc:  # pragma: no cover - depende de pywinauto
            self.error.emit(str(exc))


class StepEditor(QWidget):
    def __init__(self, macros_dir: Path):
        super().__init__()
        self.macros_dir = macros_dir
        # data/ vive junto a macros/ (ambas cuelgan de ROOT). Derivarlo de
        # macros_dir en vez de Path(__file__) es imprescindible en el .exe
        # onefile: __file__ apunta a la carpeta temporal _MEIPASS, que se
        # borra al cerrar → las incidencias/capturas del paso a paso se
        # perdían y no iban al data/ real de la app.
        self.data_dir = self.macros_dir.parent / "data"
        self.macro: Macro = Macro(nombre="nueva_macro")
        # Puntos de análisis (breakpoints): índices 0-based de pasos donde
        # el paso a paso debe detenerse. No se guardan en el YAML; son una
        # ayuda de depuración de la sesión.
        self._breakpoints: set[int] = set()
        # Ruta del YAML cargado/guardado en curso (para volver siempre al
        # mismo fichero al guardar y no pedir confirmación sobre él mismo).
        self._loaded_path: Path | None = None

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.nombre = QLineEdit(self.macro.nombre)
        self.ventana = QLineEdit()
        self.ventana.setPlaceholderText("Título de la ventana principal (regex parcial)")
        top.addWidget(QLabel("Nombre:"))
        top.addWidget(self.nombre)
        top.addWidget(QLabel("Ventana:"))
        top.addWidget(self.ventana, 1)
        layout.addLayout(top)

        salida = QHBoxLayout()
        self.carpeta_descargas = QLineEdit()
        self.carpeta_descargas.setPlaceholderText("C:/Descargas/IT")
        self.patron_renombrado = QLineEdit()
        self.patron_renombrado.setPlaceholderText("IT_{DNI}_{YYYYMMDD}.xlsx")
        salida.addWidget(QLabel("Carpeta descargas:"))
        salida.addWidget(self.carpeta_descargas, 1)
        salida.addWidget(QLabel("Patrón nombre:"))
        salida.addWidget(self.patron_renombrado, 1)
        layout.addLayout(salida)

        self.tabla = QTableWidget(0, len(COLS))
        self.tabla.setHorizontalHeaderLabels(COLS)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.verticalHeader().setVisible(False)
        layout.addWidget(self.tabla, 1)

        botones = QHBoxLayout()
        botones_def = [
            ("🔴 Grabar", self._launch_recorder, "#c0392b"),
            ("Añadir paso", self._add_step, None),
            ("Editar valor", self._edit_value, None),
            ("✓ Verificación", self._edit_verificacion, None),
            ("Eliminar", self._remove_step, None),
            ("Subir", lambda: self._move(-1), None),
            ("Bajar", lambda: self._move(1), None),
            ("Inspector", self._launch_inspector, None),
            ("⚡ Plantilla arranque", self._insertar_plantilla_arranque, "#8e44ad"),
            ("🔴 Punto análisis", self._toggle_breakpoint, "#7f2d2d"),
            ("⏸ Activar/Desactivar", self._toggle_activo, "#7f8c8d"),
            ("🐞 Paso a paso", self._launch_step_through, "#16a085"),
            ("▶ Hasta aquí", self._run_hasta_aqui, "#2980b9"),
            ("▶ Desde aquí", self._run_desde_aqui, "#2980b9"),
            ("Cargar YAML", self._load, None),
            ("Guardar YAML", self._save, None),
        ]
        for txt, slot, color in botones_def:
            b = QPushButton(txt)
            if color:
                b.setStyleSheet(f"background-color: {color}; color: white; font-weight: bold;")
            b.clicked.connect(slot)
            botones.addWidget(b)
        layout.addLayout(botones)

        self._inspector = Inspector()
        self._inspector.captured.connect(self._on_inspect_captured)
        self._inspector.error.connect(self._on_inspect_error)

    def _refresh_table(self):
        # Recordar el paso resaltado para reaplicar el highlight tras refrescar
        hl = getattr(self, "_highlighted_row", -1)
        self.tabla.setRowCount(0)
        for i, paso in enumerate(self.macro.pasos):
            self.tabla.insertRow(i)
            sel_txt = ""
            if paso.selector and not paso.selector.is_empty():
                sel_txt = paso.selector.name or paso.selector.auto_id or paso.selector.class_name or ""
                if paso.selector.control_type:
                    sel_txt = f"[{paso.selector.control_type}] {sel_txt}"
            valor = paso.valor or paso.titulo or ""
            espera = f"{paso.delay_before_s:.2f}" if paso.delay_before_s > 0 else ""
            desc = paso.descripcion
            if paso.verificar_ventana:
                desc = f"{desc}  ✓ventana:'{paso.verificar_ventana}'"
            if paso.verificar_texto:
                desc = f"{desc}  ✓texto:'{paso.verificar_texto}'"
            # Marca ● roja en la columna # si el paso es punto de análisis.
            num_txt = f"🔴 {i + 1}" if i in self._breakpoints else str(i + 1)
            valores = [
                num_txt,
                paso.tipo.value,
                sel_txt,
                valor,
                espera,
                f"{paso.timeout_s:g}",
                "✓" if paso.opcional else "",
                desc,
            ]
            for col, v in enumerate(valores):
                item = QTableWidgetItem(v)
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if not paso.activo:
                    # Paso desactivado: gris y tachado, para que se vea de
                    # un vistazo que la reproducción lo va a saltar.
                    from PyQt6.QtGui import QColor
                    f = item.font()
                    f.setStrikeOut(True)
                    item.setFont(f)
                    item.setForeground(QColor("#95a5a6"))
                self.tabla.setItem(i, col, item)
        # Re-aplicar highlight si había uno y sigue siendo válido
        if 0 <= hl < self.tabla.rowCount():
            self._aplicar_highlight(hl)

    def _aplicar_highlight(self, idx: int):
        """Pinta de fondo amarillo la fila `idx` para indicar el paso actual."""
        from PyQt6.QtGui import QBrush, QColor
        brush = QBrush(QColor("#fff3cd"))
        for c in range(self.tabla.columnCount()):
            item = self.tabla.item(idx, c)
            if item:
                item.setBackground(brush)
        self._highlighted_row = idx

    def highlight_step(self, idx: int):
        """Marca un paso como 'actual' (próximo a ejecutar) en la tabla.

        Llamado desde el panel de step-through cuando avanza al siguiente
        paso. Limpia el highlight anterior, pinta el nuevo, y hace
        scroll para que sea visible.
        """
        # Quitar highlight anterior
        prev = getattr(self, "_highlighted_row", -1)
        if 0 <= prev < self.tabla.rowCount():
            from PyQt6.QtGui import QBrush
            default_brush = QBrush()
            for c in range(self.tabla.columnCount()):
                item = self.tabla.item(prev, c)
                if item:
                    item.setBackground(default_brush)
        # Aplicar nuevo
        if 0 <= idx < self.tabla.rowCount():
            self._aplicar_highlight(idx)
            # Scroll para que se vea
            target = self.tabla.item(idx, 0)
            if target is not None:
                self.tabla.scrollToItem(target)
                self.tabla.selectRow(idx)
        else:
            self._highlighted_row = -1

    def clear_step_highlight(self):
        """Quita el highlight (lo llama el editor al cerrar step-through
        si el usuario quiere limpiar)."""
        prev = getattr(self, "_highlighted_row", -1)
        if 0 <= prev < self.tabla.rowCount():
            from PyQt6.QtGui import QBrush
            default_brush = QBrush()
            for c in range(self.tabla.columnCount()):
                item = self.tabla.item(prev, c)
                if item:
                    item.setBackground(default_brush)
        self._highlighted_row = -1

    def _sync_from_form(self):
        self.macro.nombre = self.nombre.text().strip() or "nueva_macro"
        self.macro.ventana_principal = self.ventana.text().strip()
        self.macro.salida = SalidaConfig(
            carpeta_descargas=self.carpeta_descargas.text().strip(),
            patron_renombrado=self.patron_renombrado.text().strip(),
        )

    def _sync_to_form(self):
        self.nombre.setText(self.macro.nombre)
        self.ventana.setText(self.macro.ventana_principal)
        self.carpeta_descargas.setText(self.macro.salida.carpeta_descargas)
        self.patron_renombrado.setText(self.macro.salida.patron_renombrado)

    # Tipos de paso cuyo "valor" se pide nada más crearlos (flujo más
    # intuitivo: crear → escribir el valor en el acto).
    _TIPOS_CON_VALOR = {
        StepType.TYPE_TEXT, StepType.SEND_KEYS, StepType.SLEEP,
        StepType.FOCUS_WINDOW, StepType.WAIT_FOR_WINDOW, StepType.CLOSE_WINDOW,
        StepType.LAUNCH_PROGRAM, StepType.IF_VENTANA, StepType.CLICK_OCR_TEXT,
        StepType.GET_TEXT,
    }

    def _add_step(self):
        tipos = [t.value for t in StepType]
        tipo, ok = QInputDialog.getItem(self, "Tipo de paso", "Selecciona:", tipos, 0, False)
        if not ok:
            return
        nuevo = Step(tipo=StepType(tipo), descripcion=f"Nuevo {tipo}")
        # Insertar JUSTO DESPUÉS de la fila seleccionada (más intuitivo que
        # añadir siempre al final). Si no hay selección, va al final.
        row = self.tabla.currentRow()
        insert_at = (row + 1) if row >= 0 else len(self.macro.pasos)
        self.macro.pasos.insert(insert_at, nuevo)
        from core.debug_marks import shift_on_insert
        self._breakpoints = shift_on_insert(self._breakpoints, insert_at, 1)
        self._refresh_table()
        # Dejar seleccionado el paso recién creado y, si su tipo necesita un
        # valor, abrir el editor en el acto para no tener que pulsar
        # "Editar valor" por separado.
        self.tabla.selectRow(insert_at)
        target = self.tabla.item(insert_at, 0)
        if target is not None:
            self.tabla.scrollToItem(target)
        if StepType(tipo) in self._TIPOS_CON_VALOR:
            self._edit_value()

    def _edit_value(self):
        row = self.tabla.currentRow()
        if row < 0:
            return
        paso = self.macro.pasos[row]

        # IF_VENTANA tiene un editor propio (patrón + negar + nº pasos a saltar)
        if paso.tipo == StepType.IF_VENTANA:
            self._edit_if_ventana(paso)
            return

        # CLICK_OCR_TEXT: pide texto a buscar + confianza mínima + opciones
        if paso.tipo == StepType.CLICK_OCR_TEXT:
            self._edit_click_ocr_text(paso)
            return

        # GET_TEXT: variable donde guardar + texto que debe contener
        if paso.tipo == StepType.GET_TEXT:
            self._edit_get_text(paso)
            return

        text, ok = QInputDialog.getText(self, "Editar valor", "Valor / título:", text=paso.valor or paso.titulo or "")
        if not ok:
            return
        if paso.tipo in (StepType.FOCUS_WINDOW, StepType.WAIT_FOR_WINDOW, StepType.CLOSE_WINDOW):
            paso.titulo = text
        else:
            # Si el usuario cambia el valor de un paso grabado (raw), pasa a
            # regir la semántica de placeholders: "{DNI}" debe sustituirse.
            from core.step_model import limpiar_raw_si_editado
            limpiar_raw_si_editado(paso, text)
            paso.valor = text
        self._refresh_table()

    def _edit_if_ventana(self, paso: Step):
        """Editor de un paso condicional IF_VENTANA."""
        extra = paso.extra or {}
        patron, ok = QInputDialog.getText(
            self, "Condicional: ventana",
            "Título de la ventana a comprobar (regex parcial):\n"
            "Ej: 'Error' o 'Sin datos|No hay registros'",
            text=str(extra.get("ventana", "")),
        )
        if not ok:
            return
        items = ["SÍ existe la ventana", "NO existe la ventana"]
        modo, ok2 = QInputDialog.getItem(
            self, "Condición",
            "Ejecutar el bloque siguiente cuando:",
            items, 1 if extra.get("negar") else 0, False,
        )
        if not ok2:
            return
        negar = (modo == items[1])
        saltar, ok3 = QInputDialog.getInt(
            self, "Bloque condicional",
            "¿Cuántos pasos siguientes forman el bloque 'entonces'?\n"
            "(se ejecutan si se cumple la condición, se saltan si no)",
            int(extra.get("saltar_si_no", 1)), 0, 50,
        )
        if not ok3:
            return
        paso.extra = {"ventana": patron.strip(), "negar": negar, "saltar_si_no": saltar}
        cond_txt = "NO existe" if negar else "existe"
        paso.descripcion = f"SI {cond_txt} '{patron.strip()}' → ejecuta {saltar} pasos"
        self._refresh_table()

    def _edit_click_ocr_text(self, paso: Step):
        """Editor de un paso CLICK_OCR_TEXT.

        Pide el texto a buscar y, opcionalmente, la confianza mínima
        (umbral OCR de 0-100, default 60) y si debe ser doble clic.
        """
        extra = paso.extra or {}
        texto, ok = QInputDialog.getText(
            self, "Clic sobre texto (OCR)",
            "Texto a buscar en pantalla (case-insensitive, sin acentos):\n"
            "Ej: 'Aceptar', 'Guardar como', 'INFORME'",
            text=paso.valor or "",
        )
        if not ok:
            return
        texto = texto.strip()
        if not texto:
            QMessageBox.warning(self, "Texto vacío", "Hace falta un texto a buscar.")
            return
        conf, ok2 = QInputDialog.getInt(
            self, "Confianza mínima OCR",
            "Confianza mínima del OCR (0-100). 60 es seguro, 40 más permisivo:",
            int(extra.get("min_confidence", 60)), 0, 100,
        )
        if not ok2:
            return
        items = ["Clic simple", "Doble clic"]
        modo, ok3 = QInputDialog.getItem(
            self, "Tipo de clic", "¿Cómo clicar?",
            items, 1 if extra.get("double") else 0, False,
        )
        if not ok3:
            return
        double = (modo == items[1])
        paso.valor = texto
        nueva_extra = {"min_confidence": conf}
        if double:
            nueva_extra["double"] = True
        # Mantén otras claves opcionales que el usuario haya configurado.
        for k in ("button", "region", "idioma"):
            if k in extra:
                nueva_extra[k] = extra[k]
        paso.extra = nueva_extra
        verbo = "Doble clic" if double else "Clic"
        paso.descripcion = f'{verbo} en texto "{texto}" (conf≥{conf})'
        self._refresh_table()

    def _edit_get_text(self, paso: Step):
        """Editor de un paso GET_TEXT: lee el texto del control seleccionado
        (por su selector, o de la ventana principal) y opcionalmente lo
        guarda en una variable y/o verifica que contiene un texto."""
        extra = paso.extra or {}
        var, ok = QInputDialog.getText(
            self, "Leer texto → variable",
            "Nombre de variable donde guardar el texto leído (opcional).\n"
            "Podrás usarla luego como {NOMBRE} en otros pasos.\n"
            "Ej: TEXTO_LEIDO",
            text=str(extra.get("guardar_en", "")),
        )
        if not ok:
            return
        # Validar el nombre: debe poder usarse luego como {NOMBRE}, es decir
        # casar con el regex de placeholders (letras/números/_ y sin empezar
        # por dígito). Si no, la variable se guardaría pero {..} nunca la
        # sustituiría y el usuario no se enteraría.
        var = var.strip()
        if var:
            from core.step_model import nombre_variable_valido
            if not nombre_variable_valido(var):
                QMessageBox.warning(
                    self, "Nombre de variable no válido",
                    f"'{var}' no sirve como variable.\n\n"
                    "Usa solo letras, números y guion bajo, y no empieces "
                    "por un número (ej. TEXTO_LEIDO, importe2).",
                )
                return
        contiene, ok2 = QInputDialog.getText(
            self, "Verificar contenido (opcional)",
            "Comprobar que el texto leído CONTIENE (case-insensitive, sin "
            "acentos). Vacío = no verificar.\nEj: 'Guardado' o 'correcto'",
            text=str(extra.get("contiene", "")),
        )
        if not ok2:
            return
        nueva = {}
        if var.strip():
            nueva["guardar_en"] = var.strip()
        if contiene.strip():
            nueva["contiene"] = contiene.strip()
        paso.extra = nueva
        partes = []
        if var.strip():
            partes.append(f"→ {{{var.strip().upper()}}}")
        if contiene.strip():
            partes.append(f'contiene "{contiene.strip()}"')
        paso.descripcion = "Leer texto " + (" · ".join(partes) if partes else "(sin destino)")
        self._refresh_table()

    def _edit_verificacion(self):
        """Configura la verificación post-paso del paso seleccionado:
        tras ejecutarlo, esperar a que aparezca una ventana. Si no
        aparece, se marca como incidencia."""
        row = self.tabla.currentRow()
        if row < 0:
            QMessageBox.information(self, "Selecciona un paso", "Pincha primero en una fila.")
            return
        paso = self.macro.pasos[row]
        text, ok = QInputDialog.getText(
            self, "Verificación post-paso",
            "Tras este paso, esperar a que aparezca la ventana con título "
            "(regex parcial). Déjalo vacío para no verificar.\n"
            "Ej: 'INFORMES' o 'INFORMES|FABPINF01'",
            text=paso.verificar_ventana,
        )
        if not ok:
            return
        paso.verificar_ventana = text.strip()
        # Verificación de TEXTO (además/en vez de la de ventana): comprobar
        # que el control objetivo del paso contiene un texto tras ejecutarlo.
        txt, ok_t = QInputDialog.getText(
            self, "Verificación de texto (opcional)",
            "Tras este paso, comprobar que el control (su selector, o la "
            "ventana principal) CONTIENE este texto. Vacío = no verificar.\n"
            "Ej: 'Guardado correctamente'",
            text=paso.verificar_texto,
        )
        if ok_t:
            paso.verificar_texto = txt.strip()
        if paso.verificar_ventana or paso.verificar_texto:
            seg, ok2 = QInputDialog.getInt(
                self, "Timeout de verificación",
                "Segundos máximos a esperar a la verificación:",
                int(paso.verificar_timeout_s), 1, 120,
            )
            if ok2:
                paso.verificar_timeout_s = float(seg)
        self._refresh_table()

    def _remove_step(self):
        row = self.tabla.currentRow()
        if row < 0:
            return
        del self.macro.pasos[row]
        from core.debug_marks import shift_on_remove
        self._breakpoints = shift_on_remove(self._breakpoints, row)
        self._refresh_table()

    def _move(self, delta: int):
        row = self.tabla.currentRow()
        if row < 0:
            return
        new = row + delta
        if not 0 <= new < len(self.macro.pasos):
            return
        self.macro.pasos[row], self.macro.pasos[new] = self.macro.pasos[new], self.macro.pasos[row]
        from core.debug_marks import swap_on_move
        self._breakpoints = swap_on_move(self._breakpoints, row, new)
        self._refresh_table()
        self.tabla.selectRow(new)

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Cargar macro",
            str(self.macros_dir),
            "YAML (*.yaml *.yml)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        try:
            self.macro = Macro.load(path)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo cargar: {exc}")
            return
        # El nombre que ve/edita el usuario es el del ARCHIVO, no el `nombre`
        # interno del YAML. El grabador guarda todo con nombre interno
        # "grabacion", así que cargar A.yaml mostraba "grabacion" y al
        # guardar escribía "grabacion.yaml" en vez de A.yaml (y varias
        # macros se pisaban entre sí). Con esto, cargar X.yaml → guardar
        # vuelve SIEMPRE a X.yaml.
        self.macro.nombre = Path(path).stem
        self._loaded_path = Path(path)
        self._breakpoints = set()  # los breakpoints eran de la macro anterior
        self._highlighted_row = -1  # sin highlight fantasma de la macro previa
        self._sync_to_form()
        self._refresh_table()

    def _save(self):
        """Guarda la macro a `macros/<nombre>.yaml` sin abrir diálogo de archivo.

        Evitamos QFileDialog porque el diálogo nativo de Windows usa shell
        COM y se cuelga con cierta frecuencia en apps empaquetadas con
        PyInstaller. La carpeta y el nombre vienen del propio editor.
        """
        self._sync_from_form()
        from core.step_model import nombre_archivo_macro
        nombre = nombre_archivo_macro(self.macro.nombre)
        self.macros_dir.mkdir(parents=True, exist_ok=True)
        path = self.macros_dir / nombre

        # Solo preguntamos "¿sobrescribir?" si el fichero existe Y NO es el
        # mismo que cargamos (guardar sobre el propio archivo cargado es lo
        # normal, no debe molestar con una confirmación cada vez).
        es_el_cargado = (
            getattr(self, "_loaded_path", None) is not None
            and self._loaded_path.resolve() == path.resolve()
        )
        if path.exists() and not es_el_cargado:
            resp = QMessageBox.question(
                self,
                "Sobrescribir",
                f"Ya existe '{path.name}' en la carpeta macros.\n¿Sobrescribir?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return
        # ¿Es un "guardar como" (renombrado)? El fichero anterior se conserva.
        prev = getattr(self, "_loaded_path", None)
        es_renombrado = (
            prev is not None and prev.exists()
            and prev.resolve() != path.resolve()
        )
        try:
            self.macro.save(path)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"No se pudo guardar: {exc}")
            return
        # A partir de ahora, este es el fichero "en curso": guardar de nuevo
        # (mismo nombre) irá aquí sin volver a preguntar.
        self._loaded_path = path
        msg = f"Macro guardada en:\n{path}"
        if es_renombrado:
            msg += (f"\n\nEl fichero anterior '{prev.name}' se conserva "
                    "(no se ha borrado).")
        QMessageBox.information(self, "Guardado", msg)

    def _launch_recorder(self):
        from PyQt6.QtWidgets import QDialog
        dlg = RecordDialog(self)
        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted and dlg.macro is not None and dlg.macro.pasos:
            self._on_macro_recorded(dlg.macro)
        elif result == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, "Grabación", "No se capturó ningún paso.")

    def _toggle_breakpoint(self):
        """Marca/desmarca el paso seleccionado como punto de análisis."""
        row = self.tabla.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Selecciona un paso",
                "Pincha la fila donde quieres poner (o quitar) el punto de análisis.",
            )
            return
        if row in self._breakpoints:
            self._breakpoints.discard(row)
        else:
            if not self.macro.pasos[row].activo:
                QMessageBox.warning(
                    self, "Paso desactivado",
                    f"El paso {row + 1} está desactivado: nunca se ejecuta, "
                    "así que el punto de análisis no llegaría a dispararse.\n\n"
                    "Actívalo primero.",
                )
                return
            self._breakpoints.add(row)
        self._refresh_table()
        self.tabla.selectRow(row)

    def _toggle_activo(self):
        """Activa/desactiva el paso seleccionado (sin borrarlo).

        Un paso desactivado se salta al reproducir — útil para probar sin
        él. Se marca en la tabla y se guarda como `activo: false`."""
        row = self.tabla.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "Selecciona un paso",
                "Pincha la fila que quieres activar o desactivar.",
            )
            return
        paso = self.macro.pasos[row]
        # Desactivar un condicional desactiva TAMBIÉN su bloque "entonces"
        # (si no, el bloque protegido se ejecutaría siempre). Avisamos para
        # que no sorprenda.
        if paso.activo and paso.tipo == StepType.IF_VENTANA:
            saltar = max(0, int((paso.extra or {}).get("saltar_si_no", 0)))
            if saltar and QMessageBox.question(
                self, "Desactivar condicional",
                f"Este paso es una condición que protege los {saltar} pasos "
                "siguientes.\n\nAl desactivarla se saltarán TAMBIÉN esos "
                f"{saltar} pasos (si no, se ejecutarían siempre).\n\n¿Continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
        paso.activo = not paso.activo
        self._refresh_table()
        self.tabla.selectRow(row)

    def _on_step_through_macro_modified(self):
        """El step-through insertó pasos: sincronizamos los breakpoints
        (que el panel ha desplazado) de vuelta al editor y refrescamos."""
        panel = getattr(self, "_step_panel", None)
        if panel is not None:
            bps = set(getattr(panel, "_breakpoints", self._breakpoints))
            # Restar los breakpoints temporales de la sesión (el de
            # "▶ Hasta aquí"): son de la ejecución, no marcas del usuario.
            bps -= set(getattr(panel, "_bp_temporales", set()))
            self._breakpoints = bps
        self._refresh_table()

    def _launch_step_through(self):
        """Lanza el depurador paso a paso sobre la macro.

        Si hay una fila seleccionada (que no sea la primera), pregunta si
        empezar desde el principio o DESDE ese paso — útil cuando la app
        ya está en ese punto y no quieres repetir todo lo anterior.
        """
        row = self.tabla.currentRow()
        start_idx = 0
        if row > 0:
            items = [
                "Desde el principio (paso 1)",
                f"Desde el paso {row + 1} (la app ya está en ese punto)",
            ]
            elegido, ok = QInputDialog.getItem(
                self, "¿Desde dónde?", "Empezar el paso a paso:", items, 0, False,
            )
            if not ok:
                return
            if elegido == items[1]:
                start_idx = row
        self._arrancar_step_through(start_idx=start_idx)

    def _arrancar_step_through(self, start_idx: int = 0,
                               breakpoints_extra: set | None = None):
        """Motor común para lanzar el panel de paso a paso."""
        self._sync_from_form()
        if not self.macro.pasos:
            QMessageBox.warning(self, "Macro vacía", "Añade o graba pasos antes de usar paso a paso.")
            return
        if self._ejecucion_en_curso():
            QMessageBox.information(self, "En ejecución", "Ya hay una ejecución en curso.")
            return
        # Dirs de runtime: data/ real de la app (no _MEIPASS en el .exe).
        data_dir = self.data_dir
        screenshots_dir = data_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Solo breakpoints dentro del rango actual de pasos.
        bps = {b for b in self._breakpoints if 0 <= b < len(self.macro.pasos)}
        temporales = set()
        if breakpoints_extra:
            temporales = {b for b in breakpoints_extra
                          if 0 <= b < len(self.macro.pasos)} - bps
            bps = bps | temporales
        from .step_through_panel import StepThroughPanel
        self._step_panel = StepThroughPanel(
            macro=self.macro,
            screenshots_dir=screenshots_dir,
            data_dir=data_dir,
            on_macro_modified=self._on_step_through_macro_modified,
            on_step_changed=self.highlight_step,
            breakpoints=bps,
            start_idx=start_idx,
            bp_temporales=temporales,
            parent=self,
        )
        self._step_panel.finished.connect(self._on_step_through_finished)

        # Minimizar MemoviPro para no estorbar a la app que se depura
        main_win = self.window()
        self._main_was_visible = main_win is not None and main_win.isVisible()
        if main_win is not None:
            try:
                main_win.showMinimized()
            except Exception:
                pass

        self._step_panel.start()

    def _on_step_through_finished(self):
        # Restaurar MemoviPro y refrescar tabla por si se insertaron pasos.
        main_win = self.window()
        if main_win is not None and getattr(self, "_main_was_visible", True):
            try:
                main_win.showNormal()
                main_win.raise_()
                main_win.activateWindow()
            except Exception:
                pass
        self._refresh_table()

    # ---- ejecución por rango (hasta aquí / desde aquí) ----
    def _run_hasta_aqui(self):
        """Ejecuta la macro desde el principio hasta el paso seleccionado
        (incluido) y se detiene. Útil para dejar la app en un punto
        concreto antes de seguir grabando/probando."""
        row = self.tabla.currentRow()
        if row < 0:
            QMessageBox.information(self, "Selecciona un paso",
                                    "Pincha la fila hasta la que quieres ejecutar.")
            return
        # Un paso desactivado NUNCA se ejecuta, así que un punto de parada
        # sobre él no dispararía: la macro correría entera sin supervisión.
        if not self.macro.pasos[row].activo:
            QMessageBox.warning(
                self, "Paso desactivado",
                f"El paso {row + 1} está desactivado, así que la ejecución "
                "no se detendría ahí (correría la macro entera).\n\n"
                "Actívalo primero o elige otro paso.",
            )
            return
        # Se reproduce sola hasta ese paso y SE QUEDA AHÍ EN PAUSA, dentro
        # de la sesión de depuración: así puedes grabar/insertar/saltar en
        # ese punto. (Antes terminaba la ejecución y había que empezar de
        # cero con el paso a paso para poder editar.)
        self._arrancar_step_through(start_idx=0, breakpoints_extra={row})

    def _run_desde_aqui(self):
        """Ejecuta la macro desde el paso seleccionado hasta el final.
        Útil para retomar sin repetir los pasos de arranque ya hechos."""
        row = self.tabla.currentRow()
        if row < 0:
            QMessageBox.information(self, "Selecciona un paso",
                                    "Pincha la fila desde la que quieres ejecutar.")
            return
        self._run_range(start_idx=row, stop_after_idx=None,
                        etiqueta=f"Desde el paso {row + 1}")

    def _run_range(self, start_idx: int, stop_after_idx, etiqueta: str):
        self._sync_from_form()
        if not self.macro.pasos:
            QMessageBox.warning(self, "Macro vacía", "No hay pasos que ejecutar.")
            return
        if self._ejecucion_en_curso():
            QMessageBox.information(self, "En ejecución", "Ya hay una ejecución en curso.")
            return
        self._range_abortado = False

        from pathlib import Path
        from core.replay_runner import ReplayRunner
        from .control_window import ControlWindow

        data_dir = self.data_dir
        screenshots_dir = data_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        self._range_runner = ReplayRunner(
            macro=self.macro,
            veces=1,
            velocidad=1.0,
            screenshots_dir=screenshots_dir,
            data_dir=data_dir,
            start_idx=start_idx,
            stop_after_idx=stop_after_idx,
        )
        self._range_thread = _RangeRunThread(self._range_runner)
        self._range_thread.finished_summary.connect(self._on_range_finished)
        self._range_thread.error.connect(self._on_range_error)

        # Panel flotante de control (pausa / parar) + minimizar MemoviPro.
        self._range_control = ControlWindow(parent=None)
        n = len(self.macro.pasos)
        self._range_control.set_title(f"▶ {self.macro.nombre}", etiqueta)
        ini = start_idx + 1
        fin = (stop_after_idx + 1) if stop_after_idx is not None else n
        self._range_control.set_progress(0, max(1, fin - ini + 1))
        self._range_control.set_action(f"Pasos {ini}–{fin} de {n}")
        self._range_control.pause_toggled.connect(self._on_range_pause)
        self._range_control.stop_requested.connect(self._on_range_stop)
        self._range_control.show_in_corner()

        main_win = self.window()
        self._range_main_visible = main_win is not None and main_win.isVisible()
        if main_win is not None:
            try:
                main_win.showMinimized()
            except Exception:
                pass

        self._range_thread.start()

    # ---- API para que MainWindow pueda parar el editor al cerrar/panic ----
    def hilos_en_marcha(self) -> list:
        """Hilos de ejecución del editor actualmente vivos (rango + paso a
        paso). Los usa MainWindow.closeEvent para no dejar un worker
        automatizando el escritorio tras cerrar la ventana."""
        hilos = []
        th_range = getattr(self, "_range_thread", None)
        if th_range is not None and th_range.isRunning():
            hilos.append(th_range)
        panel = getattr(self, "_step_panel", None)
        th_step = getattr(panel, "_thread", None) if panel is not None else None
        if th_step is not None and th_step.isRunning():
            hilos.append(th_step)
        return hilos

    def abort(self) -> None:
        """Aborta cualquier ejecución del editor (rango o paso a paso)."""
        # Marcar el rango como abortado por el usuario (para que el mensaje
        # final diga "detenida" y no "terminada" cuando se para por
        # pánico/cierre, que abortan el runner directamente sin pasar por
        # _on_range_stop).
        self._range_abortado = True
        runner = getattr(self, "_range_runner", None)
        if runner is not None:
            try:
                runner.abort()
            except Exception:
                pass
        panel = getattr(self, "_step_panel", None)
        if panel is not None:
            try:
                panel._on_stop()  # aborta el runner del step-through
            except Exception:
                pass
            try:
                # Liberar YA el hook global de teclado (F6-F9). Si no, en un
                # pánico el panel quedaría con las teclas capturadas hasta
                # que el worker termine de abortar.
                panel._stop_hotkeys()
            except Exception:
                pass

    def _ejecucion_en_curso(self) -> bool:
        """¿Hay un rango o un paso a paso corriendo? (guardia de solape)."""
        return bool(self.hilos_en_marcha())

    def _on_range_pause(self, paused: bool):
        runner = getattr(self, "_range_runner", None)
        if runner is None:
            return
        runner.pause() if paused else runner.resume()

    def _on_range_stop(self):
        self._range_abortado = True
        runner = getattr(self, "_range_runner", None)
        if runner is not None:
            runner.abort()

    def _on_range_finished(self, summary):
        self._cleanup_range_control()
        if getattr(self, "_range_abortado", False):
            QMessageBox.information(
                self, "Ejecución detenida",
                f"Detenida por el usuario · OK={summary.ok} · KO={summary.ko}",
            )
        else:
            QMessageBox.information(
                self, "Ejecución terminada",
                f"Rango ejecutado · OK={summary.ok} · KO={summary.ko}",
            )

    def _on_range_error(self, msg: str):
        self._cleanup_range_control()
        QMessageBox.warning(self, "Error en ejecución", msg)

    def _cleanup_range_control(self):
        ctrl = getattr(self, "_range_control", None)
        if ctrl is not None:
            try:
                ctrl.close()
                ctrl.deleteLater()
            except Exception:
                pass
            self._range_control = None
        main_win = self.window()
        if main_win is not None and getattr(self, "_range_main_visible", True):
            try:
                main_win.showNormal()
                main_win.raise_()
                main_win.activateWindow()
            except Exception:
                pass

    def _insertar_plantilla_arranque(self):
        """Inserta al PRINCIPIO de la macro la secuencia de arranque limpio.

        Abre un diálogo rico (`PlantillaArranqueDialog`) que detecta las
        ventanas abiertas, deja al usuario probar el patrón, y
        opcionalmente especificar la ruta del .exe para lanzar la app
        si no estuviera abierta.

        Pasos generados:
            [opcional] LAUNCH_PROGRAM <exe> + sleep 2s
            SEND_KEYS {VK_LWIN down}d{VK_LWIN up}   (Win+D)
            SLEEP 1s
            WINDOW_ENSURE <título> state=maximized timeout=10s
        """
        from PyQt6.QtWidgets import QDialog
        from .plantilla_arranque_dialog import PlantillaArranqueDialog

        dlg = PlantillaArranqueDialog(
            ventana_principal_actual=self.ventana.text().strip(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        titulo = dlg.titulo
        exe_path = dlg.exe_path
        if not titulo:
            QMessageBox.warning(self, "Sin título", "Necesito un patrón de título.")
            return

        nuevos: list = []
        if exe_path:
            from pathlib import Path
            nombre_exe = Path(exe_path).name or exe_path
            nuevos.append(Step(
                tipo=StepType.LAUNCH_PROGRAM,
                valor=exe_path,
                descripcion=f"Lanzar: {nombre_exe}",
                delay_before_s=0.0,
            ))
            nuevos.append(Step(
                tipo=StepType.SLEEP,
                valor="2.0",
                descripcion="Espera 2s a que arranque la aplicación",
                delay_before_s=0.0,
            ))

        nuevos += [
            Step(
                tipo=StepType.SEND_KEYS,
                valor="{VK_LWIN down}d{VK_LWIN up}",
                descripcion="Tecla Win+D  (minimizar todo)",
                delay_before_s=0.5,
            ),
            Step(
                tipo=StepType.SLEEP,
                valor="1.0",
                descripcion="Espera 1s a que se aplique Win+D",
                delay_before_s=0.0,
            ),
            Step(
                tipo=StepType.WINDOW_ENSURE,
                titulo=titulo,
                extra={"state": "maximized"},
                timeout_s=10.0,
                descripcion=f"Traer al frente + maximizar: {titulo}",
                delay_before_s=0.5,
            ),
        ]
        self.macro.pasos = nuevos + self.macro.pasos
        if not self.ventana.text().strip():
            self.ventana.setText(titulo)
        self._refresh_table()
        QMessageBox.information(
            self, "Plantilla añadida",
            f"Se insertaron {len(nuevos)} pasos al principio de la macro.\n"
            f"Patrón de ventana: '{titulo}'.",
        )

    def _on_macro_recorded(self, macro: Macro):
        if not macro or not macro.pasos:
            QMessageBox.information(self, "Grabación", "No se capturó ningún paso.")
            return
        n = len(macro.pasos)
        msg = QMessageBox(self)
        msg.setWindowTitle("Grabación completada")
        msg.setText(
            f"Se han capturado {n} pasos nuevos.\n"
            f"La macro actual tiene {len(self.macro.pasos)} pasos."
        )
        msg.setInformativeText("¿Qué quieres hacer con los pasos grabados?")
        b_anadir = msg.addButton("Añadir al final", QMessageBox.ButtonRole.AcceptRole)
        b_remplazar = msg.addButton("Reemplazar todo", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is b_anadir:
            self.macro.pasos.extend(macro.pasos)
        elif clicked is b_remplazar:
            self.macro.pasos = list(macro.pasos)
            self._breakpoints = set()  # los pasos son otros
            self._highlighted_row = -1  # sin highlight fantasma
            # Contenido nuevo: que el guardado vuelva a avisar antes de
            # sobrescribir un fichero existente con el mismo nombre.
            self._loaded_path = None
        else:
            return
        self._refresh_table()

    def _launch_inspector(self):
        QMessageBox.information(
            self,
            "Inspector",
            "Haz clic en cualquier control de la ventana objetivo.\n"
            "MemoviPro capturará su selector simbólico.",
        )
        self._inspector.empezar()

    def _on_inspect_captured(self, cap: CapturaSelector):
        row = self.tabla.currentRow()
        sel = Selector(
            control_type=cap.control_type,
            name=cap.name,
            auto_id=cap.auto_id,
            class_name=cap.class_name,
        )
        if row >= 0:
            self.macro.pasos[row].selector = sel
            self._refresh_table()
            QMessageBox.information(self, "Selector capturado", f"Aplicado al paso #{row + 1}:\n\n{cap.yaml_snippet()}")
        else:
            paso = Step(
                tipo=StepType.CLICK_CONTROL,
                selector=sel,
                descripcion=f"Click en {sel.name or sel.control_type or '?'}",
            )
            self.macro.pasos.append(paso)
            self._refresh_table()
            QMessageBox.information(self, "Selector capturado", f"Añadido como nuevo paso:\n\n{cap.yaml_snippet()}")

    def _on_inspect_error(self, msg: str):
        QMessageBox.warning(self, "Inspector", msg)
