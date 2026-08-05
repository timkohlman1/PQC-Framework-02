from pathlib import Path

SPI_IFACE = Path("Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_iface.c")
SPI_PORT = Path("ST67W6X/Target/spi_port.c")
SPI_PORT_H = Path("Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_port.h")


def test_dma_completion_uses_direct_isr_safe_semaphore():
    source = SPI_IFACE.read_text(encoding="utf-8")
    assert "SemaphoreHandle_t hw_xfer_done" in source
    assert "xSemaphoreCreateBinary" in source
    assert "xSemaphoreGiveFromISR(xfer_engine.hw_xfer_done" in source
    assert "xSemaphoreTake(engine->hw_xfer_done" in source
    callback = source[source.index("static void spi_on_transaction_complete(void)\n{") :]
    callback = callback[: callback.index("/** SPI transfer state strings */")]
    assert "xEventGroupSetBitsFromISR" not in callback


def test_stale_dma_completion_is_drained_before_each_dma_start():
    source = SPI_IFACE.read_text(encoding="utf-8")
    assert "static void spi_drain_hw_xfer_done" in source
    assert source.count("spi_drain_hw_xfer_done(engine);") >= 2
    assert "while (xSemaphoreTake(engine->hw_xfer_done, 0U) == pdTRUE)" in source


def test_timeout_aborts_only_when_transfer_is_still_active():
    source = SPI_IFACE.read_text(encoding="utf-8")
    assert source.count("if (diag.active != 0U)") >= 2
    assert 'spi_log_port_diagnostics("txrx_completion_signal_missing"' in source
    assert 'spi_log_port_diagnostics("rx_completion_signal_missing"' in source
    assert source.count("spi_port_abort_transfer();") >= 2


def test_transfer_loop_stops_after_failed_transaction():
    source = SPI_IFACE.read_text(encoding="utf-8")
    assert "int32_t xfer_result = spi_xfer_one" in source
    assert 'spi_log_port_diagnostics("xfer_failed_break_loop"' in source
    assert "if (xfer_result != 0)" in source


def test_port_records_callback_and_hal_state_evidence():
    source = SPI_PORT.read_text(encoding="utf-8")
    header = SPI_PORT_H.read_text(encoding="utf-8")
    assert "spi_port_diagnostics_t" in header
    assert "spi_port_get_diagnostics" in header
    assert "spi_port_abort_transfer" in header
    assert '#include "FreeRTOS.h"' in source
    assert '#include "task.h"' in source
    assert "spi_port_diag_begin" in source
    assert "spi_port_diag_complete" in source
    assert "HAL_SPI_Abort" in source
    assert "error_callback_count" in source


def test_invalid_header_emits_correlated_diagnostics():
    source = SPI_IFACE.read_text(encoding="utf-8")
    assert 'spi_log_port_diagnostics("invalid_header"' in source
    assert "engine_seq=" in source
    assert "port_seq=" in source
    assert "last_callback=" in source


def test_invalid_header_recovery_discards_ambiguous_frame_and_restores_boundary():
    source = SPI_IFACE.read_text(encoding="utf-8")
    assert 'spi_discard_ambiguous_txbuf(engine);' in source
    assert 'spi_recover_protocol_boundary(engine, "invalid_header_recovery")' in source
    assert 'spi_port_set_cs(0)' in source
    assert 'protocol_recovery_ready_stuck' in source
    assert 'protocol_recovery_complete' in source


def test_transaction_ready_timeout_uses_bounded_protocol_recovery():
    source = SPI_IFACE.read_text(encoding="utf-8")
    assert 'SPI_RECOVERY_READY_LOW_TIMEOUT_MS' in source
    assert 'spi_recover_protocol_boundary(engine, "txn_ready_timeout_recovery")' in source
    assert 'vTaskDelay(pdMS_TO_TICKS(SPI_RECOVERY_POLL_DELAY_MS))' in source


def test_spi_recovery_helpers_are_declared_before_use() -> None:
    source = SPI_IFACE.read_text(encoding="utf-8")
    recovery = source.index("static int32_t spi_recover_protocol_boundary")
    clear_decl = source.index("static int32_t inline spi_clear_event")
    drain_decl = source.index("static void spi_drain_hw_xfer_done")

    assert clear_decl < recovery
    assert drain_decl < recovery



def test_transaction_ready_event_is_validated_against_live_gpio_level():
    source = SPI_IFACE.read_text(encoding="utf-8")
    wait_start = source.index("static int32_t spi_wait_txn_ready(struct spi_xfer_engine *engine)\n{")
    wait_end = source.index("static void spi_drain_hw_xfer_done", wait_start)
    wait_body = source[wait_start:wait_end]

    assert "const TickType_t timeout_ticks" in wait_body
    assert "const TickType_t start_tick = xTaskGetTickCount()" in wait_body
    assert "while (true)" in wait_body
    assert wait_body.count("spi_port_is_ready() == 1") >= 3
    assert "xEventGroupWaitBits(engine->event, SPI_EVT_TXN_RDY" in wait_body
    assert "The event was stale" in wait_body
    assert "remaining = timeout_ticks - elapsed" in wait_body


def test_skip_first_wait_requires_ready_gpio_to_still_be_asserted():
    source = SPI_IFACE.read_text(encoding="utf-8")
    signature = "static int32_t spi_do_xfer(struct spi_xfer_engine *engine, uint32_t flags)\n{"
    do_xfer_start = source.index(signature)
    task_start = source.index("static void spi_xfer_engine_task", do_xfer_start)
    do_xfer = source[do_xfer_start:task_start]

    assert "wait_txn_rdy = (spi_port_is_ready() == 1) ? 0 : 1;" in do_xfer
    assert "wait_txn_rdy = 0;" not in do_xfer
