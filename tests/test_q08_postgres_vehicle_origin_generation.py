"""Run the same No.11 HTTP/constraint checks on disposable PostgreSQL."""
from test_q08_postgres_identity import DisposablePostgres
import test_q08_vehicle_origin_generation as generation


class PostgresVehicleOriginGenerationTests(DisposablePostgres, generation.VehicleOriginGenerationTests):
    pass
