from __future__ import annotations

from typing import TypedDict


class ProjectPayload(TypedDict):
    project_code: str
    customer_name: str
    project_name: str
    development_type: str
    launch_date: str | None
    packaging_date: str | None
    production_plan_date: str | None
    new_product_test_due_date: str | None
    standard_due_date: str | None
    sales_owner: str
    developer_owner: str
    mold_vendor_name: str
    supervisor_name: str
    status: str
    notes: str


class ProductPayload(TypedDict):
    project_id: int | None
    product_code: str
    product_name: str
    linked_item_id: int | None
    notes: str


class ItemPayload(TypedDict):
    project_id: int | None
    product_id: int | None
    item_code: str
    item_name: str
    item_class: str
    item_type: str
    process_type: str
    product_drawing_id: int | None
    base_print_film_id: int | None
    primary_mold_id: int | None
    base_revision_no: str
    base_material_label: str
    base_color_label: str
    mb_note: str
    notes: str


class BomPayload(TypedDict):
    project_id: int | None
    parent_item_id: int
    child_item_id: int
    qty: float
    qty_unit: str
    notes: str


class MaterialPayload(TypedDict):
    material_code: str
    material_name: str
    material_type: str
    supplier_name: str
    status: str
    backing_diameter: str
    backing_thickness: str
    backing_material_type: str
    label_film_id: int | None
    notes: str


class ProductDrawingPayload(TypedDict):
    project_id: int | None
    drawing_no: str
    drawing_name: str
    revision_no: str
    file_note: str
    file_path: str | None
    is_current: bool
    notes: str


class PrintFilmPayload(TypedDict):
    project_id: int | None
    film_code: str
    film_name: str
    artwork_type: str
    revision_no: str
    related_item_name: str
    status: str
    file_path: str | None
    notes: str
    is_current: bool


class RequirementDetailPayload(TypedDict, total=False):
    color_required: bool
    color_sample_exists: str
    color_nuance: str
    mold_change_required: bool
    mold_change_note: str
    spec_required: bool
    appearance_required: bool
    other_required: bool
    other_note: str
    post_color_required: bool
    post_masking_position: str
    post_other_note: str
    print_artwork_change_required: bool
    print_color_required: bool
    print_position_required: bool
    print_position_note: str
    print_tolerance: str
    print_other_note: str
    assembly_function_note: str
    assembly_sub_material_note: str
    assembly_other_note: str


class ExperimentOrderPayload(TypedDict):
    project_id: int
    item_id: int
    item_code: str
    process_type: str
    milestone_name: str
    base_drawing_revision: str
    drawing_receipt_status: str
    mold_pre_update: bool
    mold_dispatch_required: bool
    product_drawing_change_required: bool
    target_due_date: str | None
    milestone_due_date: str | None
    required_sample_qty: int
    experiment_goal: str
    success_criteria: str
    request_notes: str
    requirement_checks: list[str]
    detail_payload: RequirementDetailPayload
    requested_by: str


class InstructionDetailPayload(TypedDict, total=False):
    spec_check_note: str
    appearance_check_note: str
    color_check_note: str
    mold_check_note: str
    postprocess_check_note: str
    print_check_note: str
    assembly_check_note: str


class ExperimentInstructionPayload(TypedDict):
    experiment_order_id: int
    project_id: int
    item_id: int
    process_type: str
    required_sample_qty: int
    requested_finish_date: str | None
    machine_no: str
    machine_ton: str
    requirement_completed: bool
    detail_payload: dict


class ExperimentSamplePayload(TypedDict):
    order_id: int
    experiment_instruction_id: int | None
    sample_code: str
    sample_seq: int
    sample_name: str
    variation_note: str
    mold_label: str
    film_label: str
    customer_delivery_date: str | None
    customer_result_date: str | None
    customer_result: str
    customer_result_notes: str
    instruction_checks: list[str]
    detail_payload: InstructionDetailPayload
    process_type: str
    order_detail: RequirementDetailPayload
    mb_nuance: str
    mb_supplier_name: str
    mb_expected_receipt_date: str | None
    mb_sample_received: bool
    mold_dispatch_note: str
    mold_sample_request_date: str | None
    drawing_receipt_status: str
    base_drawing_revision: str


class OpReviewPayload(TypedDict):
    sample_id: int
    mold_ready: bool
    material_ready: bool
    film_ready: bool
    drawing_ready: bool
    condition_input: str
    first_measurement: str
    detail_payload: dict
    first_action: str


class QualityReviewPayload(TypedDict):
    sample_id: int
    second_measurement: str
    after_24h_measurement: str
    post_process_review: str
    assembly_review: str
    quality_comment: str


class FinalReviewPayload(TypedDict):
    sample_id: int
    final_comment: str
    final_action: str
    approval_status: str
