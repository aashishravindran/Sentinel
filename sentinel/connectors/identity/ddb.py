import aioboto3

from sentinel.core.base import IdentityConnector


class DynamoDBIdentityConnector(IdentityConnector):
    """
    DynamoDB-backed identity store.

    Expected table schema:
        Partition key: user_id (String)
        Attribute:     tags    (String Set)

    Example item:
        {"user_id": "alice", "tags": {"finance", "public"}}
    """

    def __init__(self, table_name: str, region: str = "us-east-1"):
        self.table_name = table_name
        self.region = region
        self._session = aioboto3.Session()

    async def get_tags(self, user_id: str) -> set[str]:
        async with self._session.resource("dynamodb", region_name=self.region) as ddb:
            table = await ddb.Table(self.table_name)
            response = await table.get_item(Key={"user_id": user_id})
            item = response.get("Item")
            if not item:
                return set()
            return set(item.get("tags", []))
