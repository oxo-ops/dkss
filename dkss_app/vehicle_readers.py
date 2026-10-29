"""Vehicle Readers responsibilities; routes are registered by the application factory."""
from . import common as _dkss_common, master_readers as _dkss_master_readers, models as _dkss_models, serialization as _dkss_serialization


def vehicle_number(vehicle):
    return (
        vehicle.get("number")
        or (
            f"{vehicle.get('plate_area', '')} "
            f"{vehicle.get('plate_class', '')} "
            f"{vehicle.get('plate_kana', '')} "
            f"{vehicle.get('plate_number', '')}"
        ).strip()
        or "ナンバー未登録"
    )



def delete_vehicle_related_data(vehicle):
    _dkss_models.VehicleKarteNote.query.filter_by(
        company_code=vehicle.company_code, vehicle_record_id=vehicle.id
    ).delete(synchronize_session=False)


    _dkss_models.VehicleChecklistNotifySetting.query.filter_by(
        company_code=vehicle.company_code,
        vehicle_record_id=vehicle.id
    ).delete(synchronize_session=False)



def vehicles_with_numbers(include_inactive=False):

    query = _dkss_models.Vehicle.query.filter_by(
        company_code=_dkss_common.session.get("company_code")
    )

    if not include_inactive:
        query = query.filter_by(
            deleted=False
        )

    vehicles = []

    for vehicle in query.all():

        item = {
            "index": vehicle.id,
            "id": vehicle.id,
            "company_code": vehicle.company_code,
            "vehicle_record_id": vehicle.id,
            "deleted": vehicle.deleted,

            "plate_area": vehicle.plate_area,
            "plate_class": vehicle.plate_class,
            "plate_kana": vehicle.plate_kana,
            "plate_number": vehicle.plate_number,

            "chassis_number": vehicle.chassis_number,
            "model_code": vehicle.model_code,
            "first_registration_date": vehicle.first_registration_date,
            "manufacturer": vehicle.manufacturer,
            "body_type": vehicle.body_type,

            "gross_vehicle_weight": vehicle.gross_vehicle_weight,
            "max_payload": vehicle.max_payload,

            "type": vehicle.type,
            "office": vehicle.office,
            "inspection_expiry": vehicle.inspection_expiry,
        }

        item["number"] = vehicle_number(item)

        vehicles.append(item)

    return vehicles



def vehicle_icon(vehicle_type="", body_type=""):
    import unicodedata

    def normalize(value):
        text = unicodedata.normalize(
            "NFKC",
            str(value or "")
        ).casefold()

        text = "".join(
            chr(ord(char) + 0x60)
            if "\u3041" <= char <= "\u3096"
            else char
            for char in text
        )

        return "".join(
            char
            for char in text
            if char.isalnum()
        )

    rules = [
        (
            "tractor.png",
            (
                "トラクタ",
                "トレーラーヘッド",
                "トレーラヘッド",
                "ヘッド",
                "tractor",
                "prime mover",
            )
        ),
        (
            "trailer.png",
            (
                "トレーラ",
                "トレイラ",
                "被牽引",
                "被けん引",
                "trailer",
            )
        ),
        (
            "crane.png",
            (
                "クレーン",
                "ユニック",
                "crane",
                "unic",
            )
        ),
        (
            "flatbed.png",
            (
                "平ボディ",
                "平ボデー",
                "平車",
                "フラットベッド",
                "flatbed",
            )
        ),
        (
            "car.png",
            (
                "乗用",
                "普通車",
                "軽乗用",
                "セダン",
                "passenger car",
                "sedan",
                "suv",
            )
        ),
    ]

    for value in (vehicle_type, body_type):
        text = normalize(value)

        if not text:
            continue

        for filename, aliases in rules:
            if any(
                normalize(alias) in text
                for alias in aliases
            ):
                return filename

    return "truck.png"



def vehicle_types_for_current_company():
    query = _dkss_master_readers.ordered_master_query(_dkss_models.VehicleType, _dkss_common.session.get("company_code"))

    return [
        {
            "id": vehicle_type.id,
            "master_generation": vehicle_type.master_generation,
            "index": vehicle_type.id,
            "company_code": vehicle_type.company_code,
            "name": vehicle_type.name
        }
        for vehicle_type in query.all()
    ]



def license_types_for_current_company():
    query = _dkss_master_readers.ordered_master_query(_dkss_models.LicenseType, _dkss_common.session.get("company_code"))

    return [
        {
            "id": license_type.id,
            "master_generation": license_type.master_generation,
            "index": license_type.id,
            "company_code": license_type.company_code,
            "name": license_type.name
        }
        for license_type in query.all()
    ]



def user_for_driver(driver):
    return _dkss_models.User.query.filter_by(
        company_code=driver.company_code,
        username=driver.employee_id
    ).first()



def driver_to_dict(driver):
    user = user_for_driver(driver)

    return {
        "index": driver.id,
        "id": driver.id,
        "company_code": driver.company_code,
        "employee_id": driver.employee_id,
        "username": user.username if user else "",
        "email_address": user.email_address if user else "",
        "name": driver.name,
        "role": driver.role,
        "office": driver.office,
        "safe_start_date": driver.safe_start_date,
        "vehicles": _dkss_serialization.safe_json_str_list(
            driver.vehicles_json
        ),
        "licenses": _dkss_serialization.safe_json_dict_list(
            driver.licenses_json
        ),
    }



def drivers_for_current_company():
    query = _dkss_models.Driver.query.filter_by(
        company_code=_dkss_common.session.get("company_code")
    )

    return [
        driver_to_dict(driver)
        for driver in query.all()
    ]
