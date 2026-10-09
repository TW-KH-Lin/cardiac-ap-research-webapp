#!/usr/bin/env python3
"""Qt UI for fitting voltage-like CSV traces with the ventricular AP emulator."""

from __future__ import annotations

import copy
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
import torch
from pyqtgraph.Qt import QtCore, QtWidgets

import fit_vtrace_csv_emulator as fitter


Signal = getattr(QtCore, "Signal", getattr(QtCore, "pyqtSignal"))
Slot = getattr(QtCore, "Slot", getattr(QtCore, "pyqtSlot"))
DASH_LINE = getattr(getattr(QtCore.Qt, "PenStyle", QtCore.Qt), "DashLine")


class FitWorker(QtCore.QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, kwargs: Dict[str, object]) -> None:
        super().__init__()
        self.kwargs = kwargs

    @Slot()
    def run(self) -> None:
        try:
            result = fitter.run_fit_from_csv(**self.kwargs)
        except Exception:
            self.failed.emit(traceback.format_exc())
            return
        self.finished.emit(result)


class FitWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("V-Trace Emulator Fitter")
        self.resize(1800, 1020)
        pg.setConfigOptions(antialias=True, background="w", foreground="k")

        self.emulator, _ = fitter.load_emulator()
        self._thread: Optional[QtCore.QThread] = None
        self._worker: Optional[FitWorker] = None
        self._last_run: Optional[Dict[str, object]] = None
        self._display_run: Optional[Dict[str, object]] = None
        self.mutant_change_sliders: Dict[int, QtWidgets.QSlider] = {}

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        toolbar = QtWidgets.QHBoxLayout()
        self.run_button = QtWidgets.QPushButton("Run Fit")
        self.reload_button = QtWidgets.QPushButton("Reload CSV")
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setWordWrap(True)
        toolbar.addWidget(self.run_button)
        toolbar.addWidget(self.reload_button)
        toolbar.addWidget(self.status_label, stretch=1)
        root.addLayout(toolbar)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        self.controls = self.build_controls()
        self.controls.setMinimumWidth(420)
        splitter.addWidget(self.controls)

        self.right_tabs = QtWidgets.QTabWidget()
        splitter.addWidget(self.right_tabs)
        splitter.setStretchFactor(1, 1)

        self.results_widget = QtWidgets.QWidget()
        self.results_layout = QtWidgets.QVBoxLayout(self.results_widget)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(8)
        self.right_tabs.addTab(self.results_widget, "Fit Results")

        self.trace_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.results_layout.addWidget(self.trace_splitter, stretch=1)
        self.reference_panel = self.build_trace_result_panel("Reference / Ctrl", editable=True)
        self.mutant_panel = self.build_trace_result_panel("Mutant", editable=False)
        self.trace_splitter.addWidget(self.reference_panel["container"])
        self.trace_splitter.addWidget(self.mutant_panel["container"])
        self.trace_splitter.setStretchFactor(0, 1)
        self.trace_splitter.setStretchFactor(1, 1)

        self.diagnostics = QtWidgets.QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumHeight(180)
        self.results_layout.addWidget(self.wrap_group("Diagnostics", self.diagnostics), stretch=0)
        self.emulator_note = QtWidgets.QLabel(
            "Emulator note: this fitter uses an aligned single-beat ventricular AP emulator, not an explicit paced ionic model. "
            "AP onset is learned from the training set, so very low GNa can still produce a rapid rise."
        )
        self.emulator_note.setWordWrap(True)
        self.results_layout.addWidget(self.wrap_group("Backend Note", self.emulator_note), stretch=0)

        self.validation_widget = self.build_validation_panel()
        self.right_tabs.addTab(self.validation_widget, "Mechanistic Validation")

        self.run_button.clicked.connect(self.start_fit)
        self.reload_button.clicked.connect(self.load_trace_list)
        self.csv_browse_button.clicked.connect(self.choose_csv)
        self.out_browse_button.clicked.connect(self.choose_out_prefix)
        self.linked_checkbox.toggled.connect(self.update_linked_state)
        self.trace_list.itemSelectionChanged.connect(self.update_reference_choices)
        self.use_pca_prior_checkbox.toggled.connect(self.update_pca_prior_state)
        self.reference_panel["apply_button"].clicked.connect(self.apply_manual_reference_values)
        self.reference_panel["reset_button"].clicked.connect(self.reset_manual_reference_values)
        self.validation_button.clicked.connect(self.run_mechanistic_validation)

        self.populate_direction_table()
        self.update_linked_state(self.linked_checkbox.isChecked())
        self.update_pca_prior_state(self.use_pca_prior_checkbox.isChecked())
        self.load_trace_list()
        self.reset_trace_result_panel(self.reference_panel)
        self.reset_trace_result_panel(self.mutant_panel)
        self.reset_validation_view()

    def build_controls(self) -> QtWidgets.QScrollArea:
        area = QtWidgets.QScrollArea()
        area.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        area.setWidget(container)
        form = QtWidgets.QFormLayout(container)
        form.setContentsMargins(10, 10, 10, 10)

        csv_row = QtWidgets.QHBoxLayout()
        self.csv_edit = QtWidgets.QLineEdit(str(fitter.DEFAULT_CSV))
        self.csv_browse_button = QtWidgets.QPushButton("Browse")
        csv_row.addWidget(self.csv_edit, stretch=1)
        csv_row.addWidget(self.csv_browse_button)
        form.addRow("CSV file", self.wrap_layout(csv_row))

        self.trace_list = QtWidgets.QListWidget()
        self.trace_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.trace_list.setMinimumHeight(130)
        form.addRow("V traces", self.trace_list)

        self.linked_checkbox = QtWidgets.QCheckBox("Reference -> mutant fit")
        self.linked_checkbox.setChecked(True)
        form.addRow("Fit mode", self.linked_checkbox)

        self.reference_combo = QtWidgets.QComboBox()
        self.reference_combo.setMinimumContentsLength(24)
        form.addRow("Reference trace", self.reference_combo)

        self.direction_table = QtWidgets.QTableWidget()
        self.direction_table.setColumnCount(3)
        self.direction_table.setHorizontalHeaderLabels(["Conductance", "Fit", "Mut change (%)"])
        self.direction_table.verticalHeader().setVisible(False)
        self.direction_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.direction_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.direction_table.setMinimumHeight(260)
        form.addRow("Conductance fit", self.direction_table)

        self.epochs_spin = QtWidgets.QSpinBox()
        self.epochs_spin.setRange(10, 10000)
        self.epochs_spin.setValue(200)
        form.addRow("Epochs", self.epochs_spin)

        self.max_points_spin = QtWidgets.QSpinBox()
        self.max_points_spin.setRange(50, 20000)
        self.max_points_spin.setValue(2000)
        form.addRow("Max points", self.max_points_spin)

        self.df_spin = QtWidgets.QDoubleSpinBox()
        self.df_spin.setRange(0.0, 10.0)
        self.df_spin.setDecimals(4)
        self.df_spin.setSingleStep(0.01)
        self.df_spin.setValue(0.29)
        form.addRow("dF/F0 for 100 mV", self.df_spin)

        self.rest_spin = QtWidgets.QDoubleSpinBox()
        self.rest_spin.setRange(-150.0, 50.0)
        self.rest_spin.setDecimals(1)
        self.rest_spin.setSingleStep(1.0)
        self.rest_spin.setValue(-85.0)
        form.addRow("Rest Vm (mV)", self.rest_spin)

        self.use_pca_prior_checkbox = QtWidgets.QCheckBox("Limit PCa fit range")
        self.use_pca_prior_checkbox.setChecked(True)
        form.addRow("PCa range limit", self.use_pca_prior_checkbox)

        self.allow_extrapolation_checkbox = QtWidgets.QCheckBox("Allow values above emulator training max")
        self.allow_extrapolation_checkbox.setChecked(False)
        form.addRow("Training upper cap", self.allow_extrapolation_checkbox)

        self.pca_low_spin = QtWidgets.QDoubleSpinBox()
        self.pca_low_spin.setRange(0.0, 10.0)
        self.pca_low_spin.setDecimals(2)
        self.pca_low_spin.setSingleStep(0.05)
        self.pca_low_spin.setValue(fitter.DEFAULT_PCA_PRIOR_LOW_FRAC)
        form.addRow("PCa min (x baseline)", self.pca_low_spin)

        self.pca_high_spin = QtWidgets.QDoubleSpinBox()
        self.pca_high_spin.setRange(0.0, 10.0)
        self.pca_high_spin.setDecimals(2)
        self.pca_high_spin.setSingleStep(0.05)
        self.pca_high_spin.setValue(fitter.DEFAULT_PCA_PRIOR_HIGH_FRAC)
        form.addRow("PCa max (x baseline)", self.pca_high_spin)

        self.pre_upstroke_spin = QtWidgets.QDoubleSpinBox()
        self.pre_upstroke_spin.setRange(0.0, 500.0)
        self.pre_upstroke_spin.setDecimals(1)
        self.pre_upstroke_spin.setSingleStep(5.0)
        self.pre_upstroke_spin.setValue(fitter.DEFAULT_PRE_UPSTROKE_MS)
        form.addRow("Pre-upstroke ms", self.pre_upstroke_spin)

        self.post_upstroke_spin = QtWidgets.QDoubleSpinBox()
        self.post_upstroke_spin.setRange(50.0, 2000.0)
        self.post_upstroke_spin.setDecimals(1)
        self.post_upstroke_spin.setSingleStep(10.0)
        self.post_upstroke_spin.setValue(fitter.DEFAULT_POST_UPSTROKE_MS)
        form.addRow("Post-upstroke ms", self.post_upstroke_spin)

        self.offset_clamp_spin = QtWidgets.QDoubleSpinBox()
        self.offset_clamp_spin.setRange(0.0, 500.0)
        self.offset_clamp_spin.setDecimals(1)
        self.offset_clamp_spin.setSingleStep(5.0)
        self.offset_clamp_spin.setValue(fitter.DEFAULT_TIME_OFFSET_CLAMP_MS)
        form.addRow("Max extra time shift (ms)", self.offset_clamp_spin)

        out_row = QtWidgets.QHBoxLayout()
        self.out_edit = QtWidgets.QLineEdit(str(fitter.DEFAULT_OUT_PREFIX))
        self.out_browse_button = QtWidgets.QPushButton("Save As")
        out_row.addWidget(self.out_edit, stretch=1)
        out_row.addWidget(self.out_browse_button)
        form.addRow("Output prefix", self.wrap_layout(out_row))
        return area

    @staticmethod
    def wrap_layout(layout: QtWidgets.QLayout) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        widget.setLayout(layout)
        return widget

    @staticmethod
    def wrap_group(title: str, widget: QtWidgets.QWidget) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(title)
        layout = QtWidgets.QVBoxLayout(group)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(widget)
        return group

    def build_validation_panel(self) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        controls = QtWidgets.QHBoxLayout()
        self.validation_model_choice = QtWidgets.QComboBox()
        self.validation_model_choice.addItems(fitter.available_validation_models())
        self.validation_model_choice.setCurrentText(fitter.DEFAULT_VALIDATION_MODEL)
        self.validation_auto_checkbox = QtWidgets.QCheckBox("Auto update")
        self.validation_auto_checkbox.setChecked(False)
        self.validation_button = QtWidgets.QPushButton("Run Mechanistic Validation")
        self.validation_status = QtWidgets.QLabel("Validation not run.")
        self.validation_status.setWordWrap(True)
        controls.addWidget(QtWidgets.QLabel("Model"))
        controls.addWidget(self.validation_model_choice)
        controls.addWidget(self.validation_auto_checkbox)
        controls.addWidget(self.validation_button)
        controls.addWidget(self.validation_status, stretch=1)
        layout.addLayout(controls)

        self.validation_plot = pg.PlotWidget()
        self.validation_plot.showGrid(x=True, y=True, alpha=0.25)
        self.validation_plot.setLabel("bottom", "Time", units="ms")
        self.validation_plot.setLabel("left", "Membrane Potential", units="mV")
        self.validation_plot.setMinimumHeight(240)
        layout.addWidget(self.validation_plot)

        self.validation_details = QtWidgets.QLabel("Mechanistic validation uses a published ventricular model with explicit stimulation/current balance.")
        self.validation_details.setWordWrap(True)
        layout.addWidget(self.validation_details)
        return container

    def build_trace_result_panel(self, base_title: str, editable: bool) -> Dict[str, object]:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header_row = QtWidgets.QHBoxLayout()
        title_label = QtWidgets.QLabel(base_title)
        title_label.setStyleSheet("font-weight: 600; font-size: 15px;")
        header_row.addWidget(title_label)
        header_row.addStretch(1)
        lock_checkbox = QtWidgets.QCheckBox("Lock Ctrl For Fit")
        lock_checkbox.setEnabled(False)
        apply_button = QtWidgets.QPushButton("Apply Ctrl Values")
        reset_button = QtWidgets.QPushButton("Reset Ctrl Values")
        apply_button.setEnabled(False)
        reset_button.setEnabled(False)
        if editable:
            header_row.addWidget(lock_checkbox)
            header_row.addWidget(apply_button)
            header_row.addWidget(reset_button)
        mouse_axis_combo = QtWidgets.QComboBox()
        mouse_axis_combo.addItem("Original", "target")
        mouse_axis_combo.addItem("Fit", "fit")
        mouse_axis_combo.setToolTip("Choose which Y axis responds to mouse pan/zoom for manual alignment.")
        header_row.addWidget(QtWidgets.QLabel("Mouse axis"))
        header_row.addWidget(mouse_axis_combo)
        meta_label = QtWidgets.QLabel("No fitted trace.")
        meta_label.setWordWrap(True)

        layout.addLayout(header_row)
        layout.addWidget(meta_label)

        body_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(body_splitter, stretch=1)

        plot = pg.PlotWidget()
        plot.showGrid(x=True, y=True, alpha=0.25)
        plot.setLabel("bottom", "Time", units="ms")
        plot.setLabel("left", "Original Trace", units="mV")
        plot.showAxis("right")
        plot.setLabel("right", "Fit Trace", units="mV")
        plot.setMinimumHeight(280)
        plot.getAxis("right").setStyle(showValues=True)
        fit_view = pg.ViewBox(enableMenu=False)
        plot.scene().addItem(fit_view)
        plot.getAxis("right").linkToView(fit_view)
        fit_view.setXLink(plot.getPlotItem())

        main_view = plot.getPlotItem().vb

        def sync_views() -> None:
            fit_view.setGeometry(main_view.sceneBoundingRect())
            fit_view.linkedViewChanged(main_view, fit_view.XAxis)

        main_view.sigResized.connect(sync_views)
        sync_views()
        body_splitter.addWidget(plot)

        table = QtWidgets.QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Conductance", "Value", "Delta vs ref", "Status"])
        table.verticalHeader().setVisible(False)
        if editable:
            table.setEditTriggers(
                QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
                | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed
                | QtWidgets.QAbstractItemView.EditTrigger.AnyKeyPressed
            )
            table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        else:
            table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        table.setAlternatingRowColors(True)
        table.setMinimumWidth(420)
        table.setMinimumHeight(280)
        table.horizontalHeader().setStretchLastSection(True)
        body_splitter.addWidget(table)

        body_splitter.setStretchFactor(0, 3)
        body_splitter.setStretchFactor(1, 2)

        panel: Dict[str, object] = {
            "container": container,
            "base_title": base_title,
            "editable": editable,
            "title_label": title_label,
            "meta_label": meta_label,
            "lock_checkbox": lock_checkbox,
            "apply_button": apply_button,
            "reset_button": reset_button,
            "mouse_axis_combo": mouse_axis_combo,
            "plot": plot,
            "fit_view": fit_view,
            "sync_views": sync_views,
            "table": table,
        }

        def handle_mouse_axis_change(_index: int) -> None:
            self.update_trace_plot_mouse_axis(panel)

        mouse_axis_combo.currentIndexChanged.connect(handle_mouse_axis_change)
        self.update_trace_plot_mouse_axis(panel)

        return panel

    def update_trace_plot_mouse_axis(self, panel: Dict[str, object]) -> None:
        plot = panel["plot"]
        fit_view = panel["fit_view"]
        mouse_axis_combo = panel["mouse_axis_combo"]

        assert isinstance(plot, pg.PlotWidget)
        assert isinstance(fit_view, pg.ViewBox)
        assert isinstance(mouse_axis_combo, QtWidgets.QComboBox)

        main_view = plot.getPlotItem().vb
        mode = str(mouse_axis_combo.currentData() or "target")
        all_buttons = (
            QtCore.Qt.MouseButton.LeftButton
            | QtCore.Qt.MouseButton.RightButton
            | QtCore.Qt.MouseButton.MiddleButton
        )
        if mode == "fit":
            main_view.setMouseEnabled(x=False, y=False)
            fit_view.setMouseEnabled(x=True, y=True)
            main_view.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
            fit_view.setAcceptedMouseButtons(all_buttons)
            main_view.setZValue(0)
            fit_view.setZValue(1)
        else:
            main_view.setMouseEnabled(x=True, y=True)
            fit_view.setMouseEnabled(x=False, y=False)
            main_view.setAcceptedMouseButtons(all_buttons)
            fit_view.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
            main_view.setZValue(1)
            fit_view.setZValue(0)

    def make_check_item(self, checked: bool) -> QtWidgets.QTableWidgetItem:
        item = QtWidgets.QTableWidgetItem()
        item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked)
        return item

    def make_change_slider_widget(self, value: int) -> QtWidgets.QWidget:
        slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        slider.setRange(-200, 200)
        slider.setSingleStep(5)
        slider.setPageStep(25)
        slider.setTickInterval(25)
        slider.setValue(int(value))
        label = QtWidgets.QLabel(f"{int(value):+d}%")
        label.setMinimumWidth(42)
        slider.valueChanged.connect(lambda v, out=label: out.setText(f"{int(v):+d}%"))

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(slider, stretch=1)
        layout.addWidget(label)
        widget._slider = slider  # type: ignore[attr-defined]
        return widget

    def populate_direction_table(self) -> None:
        defaults = {"PCa", "GKr", "GKs", "GK1"}
        names = fitter.available_short_names(self.emulator)
        self.mutant_change_sliders.clear()
        self.direction_table.setRowCount(len(names))
        for row, name in enumerate(names):
            name_item = QtWidgets.QTableWidgetItem(name)
            name_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.direction_table.setItem(row, 0, name_item)
            default_checked = name in defaults
            self.direction_table.setItem(row, 1, self.make_check_item(default_checked))
            slider_widget = self.make_change_slider_widget(0)
            self.direction_table.setCellWidget(row, 2, slider_widget)
            self.mutant_change_sliders[row] = slider_widget._slider  # type: ignore[attr-defined]
        self.direction_table.resizeColumnsToContents()
        self.direction_table.resizeRowsToContents()
        total_height = self.direction_table.horizontalHeader().height() + (2 * self.direction_table.frameWidth()) + 6
        for row in range(self.direction_table.rowCount()):
            total_height += self.direction_table.rowHeight(row)
        self.direction_table.setMinimumHeight(total_height)

    def choose_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose CSV",
            str(Path(self.csv_edit.text()).expanduser().parent),
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        self.csv_edit.setText(path)
        self.out_edit.setText(str(self.default_out_prefix(Path(path))))
        self.load_trace_list()

    def choose_out_prefix(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Choose output prefix",
            self.out_edit.text(),
            "CSV Prefix (*)",
        )
        if path:
            self.out_edit.setText(path)

    def default_out_prefix(self, csv_path: Path) -> Path:
        return fitter.HERE / f"{csv_path.stem}_fit_ui"

    def load_trace_list(self) -> None:
        csv_path = Path(self.csv_edit.text()).expanduser()
        try:
            _, traces, time_name = fitter.load_csv_columns(csv_path)
        except Exception as exc:
            self.status_label.setText(f"Failed to load CSV: {exc}")
            self.trace_list.clear()
            return

        self.trace_list.clear()
        for name in traces:
            item = QtWidgets.QListWidgetItem(name)
            self.trace_list.addItem(item)
        self.trace_list.selectAll()
        self.update_reference_choices()
        self.status_label.setText(f"Loaded {len(traces)} V traces from {csv_path.name} ({time_name}).")
        if not self.out_edit.text().strip():
            self.out_edit.setText(str(self.default_out_prefix(csv_path)))

    def update_linked_state(self, checked: bool) -> None:
        self.direction_table.setEnabled(checked)
        self.reference_combo.setEnabled(checked)

    def update_pca_prior_state(self, checked: bool) -> None:
        self.pca_low_spin.setEnabled(checked)
        self.pca_high_spin.setEnabled(checked)

    def selected_trace_names(self) -> List[str]:
        return [item.text() for item in self.trace_list.selectedItems()]

    def update_reference_choices(self) -> None:
        selected_names = self.selected_trace_names()
        current = self.reference_combo.currentText()
        self.reference_combo.blockSignals(True)
        self.reference_combo.clear()
        self.reference_combo.addItems(selected_names)
        if current in selected_names:
            self.reference_combo.setCurrentText(current)
        elif selected_names:
            ctrl_like = next(
                (
                    name for name in selected_names
                    if any(tag in name.lower() for tag in ("ctrl", "control", "wt", "ref", "reference"))
                ),
                selected_names[0],
            )
            self.reference_combo.setCurrentText(ctrl_like)
        self.reference_combo.blockSignals(False)

    def selected_fit_and_mutant_changes(self) -> Tuple[List[str], Dict[str, float]]:
        fit_names: List[str] = []
        mutant_changes: Dict[str, float] = {}
        for row in range(self.direction_table.rowCount()):
            name_item = self.direction_table.item(row, 0)
            fit_item = self.direction_table.item(row, 1)
            if name_item is None or fit_item is None:
                continue
            name = name_item.text()
            fit_checked = fit_item.checkState() == QtCore.Qt.CheckState.Checked
            if not fit_checked:
                continue
            fit_names.append(name)
            slider = self.mutant_change_sliders.get(row)
            if slider is None:
                continue
            delta_pct = float(slider.value())
            if abs(delta_pct) > 1e-9:
                mutant_changes[name] = delta_pct
        return fit_names, mutant_changes

    @staticmethod
    def split_name_text(text: object) -> List[str]:
        return [item for item in str(text).split(",") if item]

    def reset_trace_result_panel(self, panel: Dict[str, object]) -> None:
        title_label = panel["title_label"]
        meta_label = panel["meta_label"]
        lock_checkbox = panel["lock_checkbox"]
        apply_button = panel["apply_button"]
        reset_button = panel["reset_button"]
        mouse_axis_combo = panel["mouse_axis_combo"]
        plot = panel["plot"]
        fit_view = panel["fit_view"]
        table = panel["table"]

        assert isinstance(title_label, QtWidgets.QLabel)
        assert isinstance(meta_label, QtWidgets.QLabel)
        assert isinstance(lock_checkbox, QtWidgets.QCheckBox)
        assert isinstance(apply_button, QtWidgets.QPushButton)
        assert isinstance(reset_button, QtWidgets.QPushButton)
        assert isinstance(mouse_axis_combo, QtWidgets.QComboBox)
        assert isinstance(plot, pg.PlotWidget)
        assert isinstance(fit_view, pg.ViewBox)
        assert isinstance(table, QtWidgets.QTableWidget)

        title_label.setText(str(panel["base_title"]))
        meta_label.setText("No fitted trace.")
        lock_checkbox.setEnabled(False)
        apply_button.setEnabled(False)
        reset_button.setEnabled(False)
        mouse_axis_combo.setCurrentIndex(0)
        self.reset_plot_legend(plot)
        plot.clear()
        fit_view.clear()
        table.clearContents()
        table.setRowCount(0)
        self.update_trace_plot_mouse_axis(panel)

    def reset_validation_view(self) -> None:
        self.reset_plot_legend(self.validation_plot)
        self.validation_plot.clear()
        self.validation_status.setText("Validation not run.")
        self.validation_details.setText(
            "Mechanistic validation uses a published ventricular model with explicit stimulation/current balance."
        )

    @staticmethod
    def reset_plot_legend(plot: pg.PlotWidget) -> None:
        legend = plot.plotItem.legend
        if legend is not None:
            legend.scene().removeItem(legend)
            plot.plotItem.legend = None

    def populate_trace_result_panel(
        self,
        panel: Dict[str, object],
        trace_name: str,
        fit: Dict[str, object],
        color: object,
        reference_params: Optional[List[float]],
    ) -> None:
        title_label = panel["title_label"]
        meta_label = panel["meta_label"]
        lock_checkbox = panel["lock_checkbox"]
        apply_button = panel["apply_button"]
        reset_button = panel["reset_button"]
        mouse_axis_combo = panel["mouse_axis_combo"]
        plot = panel["plot"]
        fit_view = panel["fit_view"]
        table = panel["table"]

        assert isinstance(title_label, QtWidgets.QLabel)
        assert isinstance(meta_label, QtWidgets.QLabel)
        assert isinstance(lock_checkbox, QtWidgets.QCheckBox)
        assert isinstance(apply_button, QtWidgets.QPushButton)
        assert isinstance(reset_button, QtWidgets.QPushButton)
        assert isinstance(mouse_axis_combo, QtWidgets.QComboBox)
        assert isinstance(plot, pg.PlotWidget)
        assert isinstance(fit_view, pg.ViewBox)
        assert isinstance(table, QtWidgets.QTableWidget)

        title_label.setText(f"{panel['base_title']}: {trace_name}")
        manual_note = " | manual override active" if fit.get("manual_override_active") else ""
        meta_label.setText(
            f"Mode {fit['mode']} | RMSE Vm {float(fit['rmse_target_mv']):.3f} | "
            f"RMSE Raw {float(fit['rmse_raw_units']):.6f} | dT {float(fit['t_offset_ms']):.3f} ms{manual_note}"
        )
        lock_checkbox.setEnabled(bool(panel["editable"]))
        if bool(panel["editable"]):
            lock_checkbox.setChecked(bool(fit.get("reference_lock_active", False)))
        apply_button.setEnabled(bool(panel["editable"]))
        reset_button.setEnabled(bool(panel["editable"]) and self._last_run is not None and self._display_run is not self._last_run)

        self.reset_plot_legend(plot)
        plot.clear()
        fit_view.clear()
        plot.addLegend(offset=(10, 10))
        target_pen = pg.mkPen(color=color, width=3.6)
        fit_pen = pg.mkPen(color=color, width=2.0, style=DASH_LINE)
        target_curve = pg.PlotDataItem(fit["fit_time_ms"], fit["fit_target_mv"], pen=target_pen, name="Target")
        fit_curve = pg.PlotDataItem(fit["fit_time_ms"], fit["pred_mv"], pen=fit_pen, name="Fit")
        plot.addItem(target_curve)
        fit_view.addItem(fit_curve)
        legend = plot.plotItem.legend
        if legend is not None:
            legend.addItem(target_curve, "Target")
            legend.addItem(fit_curve, "Fit")
        sync_views = panel.get("sync_views")
        if callable(sync_views):
            sync_views()
        self.update_trace_plot_mouse_axis(panel)

        param_names = [str(name) for name in self.emulator.max_conds_names]
        short_names = fitter.available_short_names(self.emulator)
        fitted_names = set(self.split_name_text(fit.get("fitted_param_names", "")))
        values = [float(value) for value in fit["params"]]
        table.clearContents()
        table.setRowCount(len(param_names))
        for row, (param_name, short_name, value) in enumerate(zip(param_names, short_names, values)):
            delta_text = ""
            if reference_params is not None:
                ref_value = float(reference_params[row])
                if abs(ref_value) > 1e-12:
                    delta_pct = 100.0 * (value - ref_value) / ref_value
                    delta_text = f"{delta_pct:+.1f}%"
                else:
                    delta_text = "0.0%" if abs(value - ref_value) <= 1e-12 else "n/a"
            if reference_params is None:
                status = "fit" if param_name in fitted_names else "fixed"
            else:
                status = "mutant fit" if param_name in fitted_names else "control value"
            row_values = [short_name, f"{value:.6g}", delta_text, status]
            for col, text in enumerate(row_values):
                item = QtWidgets.QTableWidgetItem(text)
                if col != 1 or not bool(panel["editable"]):
                    item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable)
                else:
                    item.setFlags(
                        QtCore.Qt.ItemFlag.ItemIsEnabled
                        | QtCore.Qt.ItemFlag.ItemIsSelectable
                        | QtCore.Qt.ItemFlag.ItemIsEditable
                    )
                table.setItem(row, col, item)
        table.resizeColumnsToContents()

    def update_result_views(self, run: Dict[str, object]) -> None:
        self.reset_trace_result_panel(self.reference_panel)
        self.reset_trace_result_panel(self.mutant_panel)

        ordered_results = list(run["results"].items())
        if not ordered_results:
            return

        panels = [self.reference_panel, self.mutant_panel]
        reference_params = [float(value) for value in ordered_results[0][1]["params"]]
        for index, panel in enumerate(panels):
            if index >= len(ordered_results):
                continue
            trace_name, fit = ordered_results[index]
            color = pg.intColor(index, hues=max(8, len(ordered_results)))
            self.populate_trace_result_panel(
                panel=panel,
                trace_name=trace_name,
                fit=fit,
                color=color,
                reference_params=None if index == 0 else reference_params,
            )

    def run_mechanistic_validation(self) -> None:
        run = self._display_run or self._last_run
        if run is None or not run.get("results"):
            QtWidgets.QMessageBox.warning(self, "No fit", "Run the fitter first before mechanistic validation.")
            return

        model_name = self.validation_model_choice.currentText()
        ordered_results = list(run["results"].items())
        if not ordered_results:
            QtWidgets.QMessageBox.warning(self, "No fit", "No fitted traces are available for validation.")
            return

        self.validation_status.setText("Running mechanistic validation...")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        QtWidgets.QApplication.processEvents()
        try:
            validations = []
            for trace_name, fit in ordered_results[:2]:
                validations.append((trace_name, fit, fitter.simulate_mechanistic_validation(model_name, fit["params"])))
        except Exception as exc:
            self.validation_status.setText(f"Validation failed: {exc}")
            details = traceback.format_exc()
            self.validation_details.setText(details)
            QtWidgets.QMessageBox.critical(self, "Validation error", details)
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self.reset_plot_legend(self.validation_plot)
        self.validation_plot.clear()
        self.validation_plot.addLegend(offset=(10, 10))
        detail_lines = []
        for index, (trace_name, fit, validation) in enumerate(validations):
            color = pg.intColor(index, hues=max(8, len(validations)))
            display_pen = pg.mkPen(color=color, width=1.6, style=DASH_LINE)
            mech_pen = pg.mkPen(color=color, width=2.6)
            self.validation_plot.plot(
                np.asarray(fit["fit_time_ms"], dtype=float),
                np.asarray(fit["pred_mv"], dtype=float),
                pen=display_pen,
                name=f"{trace_name} emulator",
            )
            result = validation["result"]
            if result.voltage_mv is not None:
                self.validation_plot.plot(
                    np.asarray(result.time_ms, dtype=float),
                    np.asarray(result.voltage_mv, dtype=float),
                    pen=mech_pen,
                    name=f"{trace_name} mechanistic",
                )
            settings = validation["settings"]
            mapped = ", ".join(validation["mapped_params"]) or "none"
            ignored = ", ".join(validation["ignored_params"]) or "none"
            detail_lines.append(
                f"{trace_name}: paced {settings['stim_frequency_hz']} Hz, {settings['stim_duration_ms']} ms, "
                f"{settings['stim_strength_nA']} nA, prepace {settings['prepace_beats']} | mapped {mapped} | ignored {ignored}"
            )
            if getattr(result, "warning", None):
                detail_lines.append(f"{trace_name} warning: {result.warning}")

        self.validation_plot.setTitle(f"Mechanistic validation: {model_name}")
        self.validation_status.setText(f"Validated with {model_name}.")
        self.validation_details.setText("\n".join(detail_lines))

    def manual_reference_params_from_table(self) -> List[float]:
        table = self.reference_panel["table"]
        assert isinstance(table, QtWidgets.QTableWidget)
        if table.rowCount() != len(self.emulator.max_conds_names):
            raise ValueError("Run the control fit first so the full control conductance table is available.")
        values: List[float] = []
        for row in range(table.rowCount()):
            item = table.item(row, 1)
            if item is None:
                raise ValueError(f"Missing control value at row {row + 1}.")
            text = item.text().strip()
            if not text:
                raise ValueError(f"Empty control value at row {row + 1}.")
            values.append(float(text))
        return values

    def clamp_params_to_current_bounds(self, params: List[float]) -> Tuple[List[float], List[str]]:
        clipped, messages, _, _ = fitter.clamp_param_vector_to_bounds(
            self.emulator,
            params,
            use_pca_prior=self.use_pca_prior_checkbox.isChecked(),
            pca_prior_low_frac=float(self.pca_low_spin.value()),
            pca_prior_high_frac=float(self.pca_high_spin.value()),
            allow_training_extrapolation=self.allow_extrapolation_checkbox.isChecked(),
        )
        return [float(value) for value in clipped], messages

    def set_reference_table_values(self, values: List[float]) -> None:
        table = self.reference_panel["table"]
        assert isinstance(table, QtWidgets.QTableWidget)
        if table.rowCount() != len(values):
            return
        for row, value in enumerate(values):
            item = table.item(row, 1)
            if item is None:
                item = QtWidgets.QTableWidgetItem()
                table.setItem(row, 1, item)
            item.setText(f"{float(value):.6g}")

    def recompute_fit_with_params(self, fit: Dict[str, object], params: List[float], mode_prefix: str) -> Dict[str, object]:
        updated = dict(fit)
        params_np = np.asarray(params, dtype=np.float32)
        fit_time_ms = np.asarray(fit["fit_time_ms"], dtype=np.float32)
        fit_raw = np.asarray(fit["fit_raw"], dtype=float)
        fit_target_mv = np.asarray(fit["fit_target_mv"], dtype=float)
        t_offset_ms = float(fit["t_offset_ms"])

        with torch.no_grad():
            time_t = torch.from_numpy(fit_time_ms).to(self.emulator.device)
            params_t = torch.from_numpy(params_np).to(self.emulator.device)
            pred_mv = self.emulator.forward_latent(time_t + t_offset_ms, params_t[None])[0].detach().cpu().numpy().astype(float)

        df_scale = float(fit.get("df_for_100mv", float("nan")))
        if np.isnan(df_scale):
            scale_to_raw, offset_to_raw, pred_raw_units = fitter.affine_fit(pred_mv, fit_raw)
        else:
            assumed_rest_mv = float(fit["assumed_rest_mv"])
            estimated_rest_df = float(fit["estimated_rest_df"])
            mv_per_df = 100.0 / df_scale
            pred_raw_units = (pred_mv - assumed_rest_mv) / mv_per_df + estimated_rest_df
            scale_to_raw = 1.0 / mv_per_df
            offset_to_raw = estimated_rest_df - assumed_rest_mv / mv_per_df

        updated["mode"] = f"{mode_prefix}-{fit['mode']}"
        updated["params"] = params_np.astype(float)
        updated["pred_mv"] = pred_mv
        updated["pred_raw_units"] = pred_raw_units
        updated["scale_to_raw"] = scale_to_raw
        updated["offset_to_raw"] = offset_to_raw
        updated["rmse_target_mv"] = fitter.rmse(pred_mv, fit_target_mv)
        updated["rmse_raw_units"] = fitter.rmse(pred_raw_units, fit_raw)
        updated["manual_override_active"] = True
        updated["reference_lock_active"] = True
        return updated

    def apply_manual_reference_values(self) -> None:
        if self._last_run is None or self._display_run is None:
            return
        try:
            reference_values = self.manual_reference_params_from_table()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid control value", str(exc))
            return
        reference_values, reference_clamp_messages = self.clamp_params_to_current_bounds(reference_values)
        if reference_clamp_messages:
            self.set_reference_table_values(reference_values)

        run = copy.deepcopy(self._last_run)
        ordered_names = list(run["results"].keys())
        if not ordered_names:
            return
        reference_name = ordered_names[0]
        reference_fit = self.recompute_fit_with_params(run["results"][reference_name], reference_values, "manual")
        run["results"][reference_name] = reference_fit

        if len(ordered_names) > 1:
            mutant_name = ordered_names[1]
            mutant_fit = run["results"][mutant_name]
            mutant_values = np.asarray(mutant_fit["params"], dtype=float).copy()
            mutant_fitted_names = set(self.split_name_text(mutant_fit.get("fitted_param_names", "")))
            mutant_change_limits = self.selected_fit_and_mutant_changes()[1]
            param_names = [str(name) for name in self.emulator.max_conds_names]
            for idx, param_name in enumerate(param_names):
                ref_value = float(reference_values[idx])
                if param_name not in mutant_fitted_names:
                    mutant_values[idx] = ref_value
                    continue
                short_name = fitter.available_short_names(self.emulator)[idx]
                change_limit = mutant_change_limits.get(short_name)
                if change_limit is None:
                    continue
                target_value = ref_value * (1.0 + change_limit / 100.0)
                lower = min(ref_value, target_value)
                upper = max(ref_value, target_value)
                mutant_values[idx] = float(np.clip(mutant_values[idx], lower, upper))

            mutant_values_list, mutant_clamp_messages = self.clamp_params_to_current_bounds(list(mutant_values))
            run["results"][mutant_name] = self.recompute_fit_with_params(mutant_fit, mutant_values_list, "manual")
        else:
            mutant_clamp_messages = []

        clamp_messages = list(reference_clamp_messages) + [f"mutant {message}" for message in mutant_clamp_messages]
        if clamp_messages:
            clamp_summary = " | ".join(clamp_messages)
            for fit in run["results"].values():
                fit["reference_lock_clamped"] = True
                fit["reference_lock_clamp_summary"] = clamp_summary
        else:
            for fit in run["results"].values():
                fit["reference_lock_clamped"] = False
                fit["reference_lock_clamp_summary"] = ""

        self._display_run = run
        lock_checkbox = self.reference_panel["lock_checkbox"]
        assert isinstance(lock_checkbox, QtWidgets.QCheckBox)
        lock_checkbox.setChecked(True)
        self.update_result_views(run)
        self.update_diagnostics(run)
        status_text = "Applied manual control conductance values."
        if clamp_messages:
            status_text += f" Clipped {len(clamp_messages)} value(s) to model bounds."
        self.status_label.setText(status_text)
        if self.validation_auto_checkbox.isChecked():
            self.run_mechanistic_validation()

    def reset_manual_reference_values(self) -> None:
        if self._last_run is None:
            return
        lock_checkbox = self.reference_panel["lock_checkbox"]
        assert isinstance(lock_checkbox, QtWidgets.QCheckBox)
        lock_checkbox.setChecked(False)
        self._display_run = self._last_run
        self.update_result_views(self._last_run)
        self.update_diagnostics(self._last_run)
        self.status_label.setText("Reset to fitted control values.")
        if self.validation_auto_checkbox.isChecked():
            self.run_mechanistic_validation()

    def start_fit(self) -> None:
        csv_path = Path(self.csv_edit.text()).expanduser()
        trace_names = self.selected_trace_names()
        if not trace_names:
            QtWidgets.QMessageBox.warning(self, "No traces", "Select at least one V-trace.")
            return

        fit_param_names, mutant_change_limits = self.selected_fit_and_mutant_changes()
        if not fit_param_names:
            QtWidgets.QMessageBox.warning(
                self,
                "No conductances",
                "Tick Fit for at least one conductance.",
            )
            return

        force_linked = self.linked_checkbox.isChecked()
        linked_different: List[str] = []
        reference_locked_params: Optional[Tuple[float, ...]] = None
        if force_linked:
            if len(trace_names) != 2:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Need ctrl and mut",
                    "Reference -> mutant fitting requires exactly two selected traces.",
                )
                return
            reference_name = self.reference_combo.currentText().strip()
            if reference_name:
                if reference_name not in trace_names:
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Reference trace",
                        "Select the reference trace from the currently selected V traces.",
                    )
                    return
                trace_names = [reference_name] + [name for name in trace_names if name != reference_name]
            linked_different = list(mutant_change_limits.keys())
            lock_checkbox = self.reference_panel["lock_checkbox"]
            assert isinstance(lock_checkbox, QtWidgets.QCheckBox)
            if lock_checkbox.isChecked():
                try:
                    reference_locked_params = tuple(self.manual_reference_params_from_table())
                except ValueError as exc:
                    QtWidgets.QMessageBox.warning(self, "Invalid control value", str(exc))
                    return

        kwargs = {
            "csv_path": csv_path,
            "trace_names": trace_names,
            "epochs": int(self.epochs_spin.value()),
            "max_points": int(self.max_points_spin.value()),
            "df_for_100mv": float(self.df_spin.value()) if self.df_spin.value() > 0 else None,
            "rest_mv": float(self.rest_spin.value()),
            "fit_param_names": tuple(fit_param_names),
            "linked_different": tuple(linked_different),
            "direction_constraints": {},
            "mutant_change_limits_pct": mutant_change_limits,
            "reference_locked_params": reference_locked_params,
            "allow_training_extrapolation": self.allow_extrapolation_checkbox.isChecked(),
            "use_pca_prior": self.use_pca_prior_checkbox.isChecked(),
            "pca_prior_low_frac": float(self.pca_low_spin.value()),
            "pca_prior_high_frac": float(self.pca_high_spin.value()),
            "pre_upstroke_ms": float(self.pre_upstroke_spin.value()),
            "post_upstroke_ms": float(self.post_upstroke_spin.value()),
            "time_offset_clamp_ms": float(self.offset_clamp_spin.value()),
            "force_linked": force_linked,
            "out_prefix": Path(self.out_edit.text()).expanduser() if self.out_edit.text().strip() else None,
        }

        self.run_button.setEnabled(False)
        self.status_label.setText("Running fit...")

        self._thread = QtCore.QThread(self)
        self._worker = FitWorker(kwargs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self.handle_fit_success)
        self._worker.failed.connect(self.handle_fit_failure)
        self._worker.finished.connect(self.cleanup_worker)
        self._worker.failed.connect(self.cleanup_worker)
        self._thread.start()

    @Slot(object)
    def handle_fit_success(self, run: Dict[str, object]) -> None:
        self._last_run = run
        self._display_run = run
        self.update_result_views(run)
        self.update_diagnostics(run)
        summary_path = run.get("summary_path")
        self.status_label.setText(f"Fit completed. Summary: {summary_path}")
        if self.validation_auto_checkbox.isChecked():
            self.run_mechanistic_validation()

    @Slot(str)
    def handle_fit_failure(self, details: str) -> None:
        self.status_label.setText("Fit failed.")
        self.diagnostics.setPlainText(details)
        QtWidgets.QMessageBox.critical(self, "Fit failed", details)

    @Slot()
    def cleanup_worker(self) -> None:
        self.run_button.setEnabled(True)
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None

    def update_diagnostics(self, run: Dict[str, object]) -> None:
        lines = [
            f"Time column: {run['time_name']}",
            f"Selected traces: {', '.join(run['trace_names'])}",
        ]
        summary_path = run.get("summary_path")
        traces_path = run.get("traces_path")
        if summary_path is not None:
            lines.append(f"Summary CSV: {summary_path}")
        if traces_path is not None:
            lines.append(f"Trace CSV: {traces_path}")

        results = run["results"]
        first = next(iter(results.values()))
        fit_strategy = str(first.get("fit_strategy", ""))
        fitted = first.get("fitted_param_names", "")
        fixed = first.get("fixed_param_names", "")
        linked = first.get("linked_different_params", "")
        directions = first.get("mut_direction_constraints", "")
        mutant_changes = first.get("mutant_change_limits_pct", "")
        shared = first.get("shared_param_names", "")
        pca_enabled = bool(first.get("pca_prior_enabled", True))
        training_extrapolation_enabled = bool(first.get("training_extrapolation_enabled", False))
        reference_lock_active = bool(first.get("reference_lock_active", False))
        reference_lock_clamped = bool(first.get("reference_lock_clamped", False))
        reference_lock_clamp_summary = str(first.get("reference_lock_clamp_summary", ""))
        if fit_strategy:
            lines.append(f"Fit strategy: {fit_strategy}")
        if reference_lock_active:
            lines.append("Reference lock: active")
        lines.append(
            "Training upper cap: disabled, allowing extrapolation above emulator max"
            if training_extrapolation_enabled
            else "Training upper cap: enabled, using emulator training max"
        )
        if reference_lock_clamped:
            lines.append("Reference lock bounds: clipped to allowed model range")
            if reference_lock_clamp_summary:
                lines.append(f"Reference lock clipping: {reference_lock_clamp_summary}")
        if fitted:
            lines.append(f"Reference fitted conductances: {fitted}")
        if fixed:
            lines.append(f"Reference fixed conductances: {fixed}")
        if pca_enabled:
            lines.append(f"PCa allowed range: {float(first['pca_prior_low_frac']):.2f}x to {float(first['pca_prior_high_frac']):.2f}x baseline")
        else:
            lines.append("PCa allowed range: disabled, using emulator default bounds")
        if linked:
            lines.append(f"Mutant-changing conductances: {linked}")
        if mutant_changes:
            lines.append(f"Mutant change limits: {mutant_changes}")
        if directions:
            lines.append(f"Mut direction constraints: {directions}")
        if shared:
            lines.append(f"Inherited from reference: {shared}")
        if fit_strategy == "reference_then_mutant" and len(run["trace_names"]) == 2:
            lines.append(f"Reference trace: {run['trace_names'][0]}")
            lines.append(f"Mutant trace: {run['trace_names'][1]}")

        lines.append("")
        for trace_name, fit in results.items():
            lines.append(f"{trace_name}")
            lines.append(f"  mode: {fit['mode']}")
            lines.append(f"  rmse_target_mv: {float(fit['rmse_target_mv']):.3f}")
            lines.append(f"  rmse_raw_units: {float(fit['rmse_raw_units']):.6f}")
            lines.append(f"  t_offset_ms: {float(fit['t_offset_ms']):.3f}")
            lines.append(f"  estimated_rest_df: {float(fit['estimated_rest_df']):.6f}")
            lines.append(f"  assumed_rest_mv: {float(fit['assumed_rest_mv']):.1f}")
            if fit.get("pca_prior_enabled", True):
                lines.append(f"  pca_range: {float(fit['pca_prior_low_frac']):.2f}x to {float(fit['pca_prior_high_frac']):.2f}x baseline")
            else:
                lines.append("  pca_range: disabled, using emulator default bounds")
            lines.append(
                f"  alignment: upstroke {float(fit['upstroke_time_ms']):.1f} ms, "
                f"window {float(fit['pre_upstroke_ms']):.1f}/{float(fit['post_upstroke_ms']):.1f} ms, "
                f"clamp {float(fit['time_offset_clamp_ms']):.1f} ms"
            )

        self.diagnostics.setPlainText("\n".join(lines))


def main() -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = FitWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
