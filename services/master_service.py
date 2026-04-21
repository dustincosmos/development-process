from __future__ import annotations

from db import master_repository
from domain.schemas import (
    BomPayload,
    ItemPayload,
    MaterialPayload,
    PrintFilmPayload,
    ProductPayload,
    ProductDrawingPayload,
    ProjectPayload,
)


def delete_project(project_id: int) -> tuple[bool, str]:
    return master_repository.delete_project(project_id)


def save_project(selected_project_id: int | None, payload: ProjectPayload, current_user_name: str) -> None:
    master_repository.save_project(selected_project_id, payload, current_user_name)


def delete_product(product_id: int) -> tuple[bool, str]:
    return master_repository.delete_product(product_id)


def save_product(selected_product_id: int | None, payload: ProductPayload, current_user_name: str) -> None:
    master_repository.save_product(selected_product_id, payload, current_user_name)


def delete_item(item_id: int) -> tuple[bool, str]:
    return master_repository.delete_item(item_id)


def save_item(selected_item_id: int | None, payload: ItemPayload, current_user_name: str) -> None:
    master_repository.save_item(selected_item_id, payload, current_user_name)


def delete_bom(bom_id: int) -> tuple[bool, str]:
    return master_repository.delete_bom(bom_id)


def save_bom(selected_bom_id: int | None, payload: BomPayload, current_user_name: str) -> None:
    master_repository.save_bom(selected_bom_id, payload, current_user_name)


def delete_raw_material(raw_material_id: int) -> tuple[bool, str]:
    return master_repository.delete_raw_material(raw_material_id)


def save_raw_material(selected_raw_material_id: int | None, payload: MaterialPayload, current_user_name: str) -> None:
    master_repository.save_raw_material(selected_raw_material_id, payload, current_user_name)


def delete_sub_material(sub_material_id: int) -> tuple[bool, str]:
    return master_repository.delete_sub_material(sub_material_id)


def save_sub_material(selected_sub_material_id: int | None, payload: MaterialPayload, current_user_name: str) -> None:
    master_repository.save_sub_material(selected_sub_material_id, payload, current_user_name)


def delete_product_drawing(product_drawing_id: int) -> tuple[bool, str]:
    return master_repository.delete_product_drawing(product_drawing_id)


def save_product_drawing(
    selected_product_drawing_id: int | None,
    *,
    create_new_revision: bool,
    payload: ProductDrawingPayload,
    current_user_name: str,
) -> None:
    master_repository.save_product_drawing(
        selected_product_drawing_id,
        create_new_revision=create_new_revision,
        payload=payload,
        current_user_name=current_user_name,
    )


def delete_print_film(print_film_id: int) -> tuple[bool, str]:
    return master_repository.delete_print_film(print_film_id)


def save_print_film(
    selected_print_film_id: int | None,
    *,
    create_new_revision: bool,
    payload: PrintFilmPayload,
    current_user_name: str,
) -> None:
    master_repository.save_print_film(
        selected_print_film_id,
        create_new_revision=create_new_revision,
        payload=payload,
        current_user_name=current_user_name,
    )
