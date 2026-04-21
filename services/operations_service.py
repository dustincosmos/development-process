from __future__ import annotations

import time

from db import operations_repository


def _log_wms_step(name: str, start_time: float) -> None:
    elapsed = time.perf_counter() - start_time
    print(f"[WMS] {name}: {elapsed:.3f}s")


def list_mold_dispatch_orders():
    return operations_repository.list_mold_dispatch_orders()


def list_molds():
    return operations_repository.list_molds()


def execute_mold_dispatch(
    mold_dispatch_order_id: int,
    *,
    mold_id: int | None,
    sample_request_date: str | None,
    dispatch_date: str | None,
    modification_note: str,
) -> None:
    operations_repository.execute_mold_dispatch(
        mold_dispatch_order_id,
        mold_id=mold_id,
        sample_request_date=sample_request_date,
        dispatch_date=dispatch_date,
        modification_note=modification_note,
    )


def complete_mold_dispatch_receipt(
    mold_dispatch_order_id: int,
    *,
    receipt_date: str,
    modification_note: str,
) -> None:
    operations_repository.complete_mold_dispatch_receipt(
        mold_dispatch_order_id,
        receipt_date=receipt_date,
        modification_note=modification_note,
    )


def list_mb_requests():
    return operations_repository.list_mb_requests()


def sync_mb_request_receipt_statuses() -> None:
    operations_repository.sync_mb_request_receipt_statuses()


def save_mb_request_consultation(
    mb_request_id: int,
    *,
    sample_sent: bool,
    supplier_name: str,
    consultation_note: str,
    expected_receipt_date: str | None,
) -> None:
    operations_repository.save_mb_request_consultation(
        mb_request_id,
        sample_sent=sample_sent,
        supplier_name=supplier_name,
        consultation_note=consultation_note,
        expected_receipt_date=expected_receipt_date,
    )


def create_mb_purchase_request(
    mb_request_id: int,
    *,
    sample_sent: bool,
    supplier_name: str,
    consultation_note: str,
    expected_receipt_date: str,
) -> None:
    operations_repository.create_mb_purchase_request(
        mb_request_id,
        sample_sent=sample_sent,
        supplier_name=supplier_name,
        consultation_note=consultation_note,
        expected_receipt_date=expected_receipt_date,
    )


def delete_mb_request(mb_request_id: int) -> tuple[bool, str]:
    return operations_repository.delete_mb_request(mb_request_id)


def list_mb_receipts():
    return operations_repository.list_mb_receipts()


def save_mb_receipt(
    *,
    mb_request_id: int,
    receipt_date: str | None,
    receipt_qty: float,
    lot_no: str,
    receipt_note: str,
    current_user_name: str,
    existing_receipt_id: int | None = None,
) -> dict[str, str | float | int | None]:
    return operations_repository.save_mb_receipt(
        mb_request_id=mb_request_id,
        receipt_date=receipt_date,
        receipt_qty=receipt_qty,
        lot_no=lot_no,
        receipt_note=receipt_note,
        current_user_name=current_user_name,
        existing_receipt_id=existing_receipt_id,
    )


def delete_mb_receipt(mb_receipt_id: int, *, mb_request_id: int) -> tuple[bool, str]:
    return operations_repository.delete_mb_receipt(mb_receipt_id, mb_request_id=mb_request_id)


def list_project_options():
    return operations_repository.list_project_options()


def list_experiment_samples():
    return operations_repository.list_experiment_samples()


def list_postprocess_item_moves():
    return operations_repository.list_postprocess_item_moves()


def list_sample_inventory():
    return operations_repository.list_sample_inventory()


def prepare_wms(*, current_user_name: str) -> None:
    total_start = time.perf_counter()

    t0 = time.perf_counter()
    operations_repository.sync_sample_inventory(current_user_name=current_user_name)
    _log_wms_step("sync_sample_inventory", t0)

    t0 = time.perf_counter()
    operations_repository.sync_wms_orders_from_stock_requirements(current_user_name=current_user_name)
    _log_wms_step("sync_wms_orders_from_stock_requirements", t0)

    t0 = time.perf_counter()
    operations_repository.sync_wms_orders_from_customer_requirements(current_user_name=current_user_name)
    _log_wms_step("sync_wms_orders_from_customer_requirements", t0)

    t0 = time.perf_counter()
    operations_repository.sync_wms_inbound_plans_from_instructions(current_user_name=current_user_name)
    _log_wms_step("sync_wms_inbound_plans_from_instructions", t0)

    _log_wms_step("prepare_wms_total", total_start)


def recalculate_inventory_reservations(*, current_user_name: str) -> None:
    operations_repository.recalculate_inventory_reservations(current_user_name=current_user_name)


def sync_customer_dispatch_for_sample(*, sample_id: int, current_user_name: str) -> None:
    operations_repository.sync_sample_inventory(current_user_name=current_user_name)
    operations_repository.sync_wms_orders_from_customer_requirements(current_user_name=current_user_name)
    operations_repository.sync_customer_dispatch_for_sample(sample_id=sample_id, current_user_name=current_user_name)


def sync_customer_dispatch_orders(*, current_user_name: str) -> None:
    operations_repository.sync_wms_orders_from_customer_requirements(current_user_name=current_user_name)


def save_postprocess_dispatch(
    *,
    sample_id: int,
    project_id: int,
    item_id: int,
    vendor_name: str,
    child_dispatch_note: str,
    dispatch_date: str,
    expected_receipt_date: str | None,
    current_user_name: str,
    postprocess_move_id: int | None = None,
) -> None:
    operations_repository.save_postprocess_dispatch(
        sample_id=sample_id,
        project_id=project_id,
        item_id=item_id,
        vendor_name=vendor_name,
        child_dispatch_note=child_dispatch_note,
        dispatch_date=dispatch_date,
        expected_receipt_date=expected_receipt_date,
        current_user_name=current_user_name,
        postprocess_move_id=postprocess_move_id,
    )


def complete_postprocess_receipt(postprocess_move_id: int, *, receipt_date: str) -> None:
    operations_repository.complete_postprocess_receipt(postprocess_move_id, receipt_date=receipt_date)


def delete_postprocess_move(postprocess_move_id: int) -> tuple[bool, str]:
    return operations_repository.delete_postprocess_move(postprocess_move_id)


def execute_wms_dispatch(
    *,
    postprocess_move_id: int,
    sample_id: int,
    dispatch_qty: float,
    dispatch_date: str,
    from_location: str,
    to_location: str,
    partner_name: str,
    current_user_name: str,
) -> None:
    operations_repository.execute_wms_dispatch(
        postprocess_move_id=postprocess_move_id,
        sample_id=sample_id,
        dispatch_qty=dispatch_qty,
        dispatch_date=dispatch_date,
        from_location=from_location,
        to_location=to_location,
        partner_name=partner_name,
        current_user_name=current_user_name,
    )


def complete_wms_receipt(
    *,
    postprocess_move_id: int,
    receipt_date: str,
    receipt_qty: float,
    to_location: str,
    partner_name: str,
    receipt_note: str,
    unit_cost: float | None,
    uph: float | None,
    defect_rate: float | None,
    moq: float | None,
    current_user_name: str,
) -> None:
    operations_repository.complete_wms_receipt(
        postprocess_move_id=postprocess_move_id,
        receipt_date=receipt_date,
        receipt_qty=receipt_qty,
        to_location=to_location,
        partner_name=partner_name,
        receipt_note=receipt_note,
        unit_cost=unit_cost,
        uph=uph,
        defect_rate=defect_rate,
        moq=moq,
        current_user_name=current_user_name,
    )


def adjust_sample_inventory(
    *,
    sample_id: int,
    project_id: int,
    item_id: int,
    qty_delta: float,
    reason: str,
    note: str,
    current_user_name: str,
) -> None:
    operations_repository.adjust_sample_inventory(
        sample_id=sample_id,
        project_id=project_id,
        item_id=item_id,
        qty_delta=qty_delta,
        reason=reason,
        note=note,
        current_user_name=current_user_name,
    )
