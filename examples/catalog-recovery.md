# Recover the previous catalog snapshot

Use this procedure if the published catalog fails to download, its CSV header
differs from the public feed contract, or its row count differs from the
reviewed candidate. Record the observed failure and the public file's timestamp.

Select the dated archive copy from immediately before this publication. Open
that copy and verify its header and row count against the previous snapshot's
review notes before using it. If the archive is missing or cannot be validated,
leave the public filename in place and escalate to the library operations lead.

Restore the validated archive copy as `catalog-public.csv` through the Catalog
Admin **Exports** screen. Download the restored public file and check the
header and row count against the archive. Record the restored archive's date
and send the incident details to the library operations lead.
