# Monthly catalog export

The library operations team publishes one catalog snapshot each month. Produce
the candidate from the Catalog Admin **Exports** screen with the saved
`public-monthly` preset. Save the downloadable CSV as `catalog-candidate.csv`.
Keep the current `catalog-public.csv` untouched during review.

Open the candidate as UTF-8 CSV. The header must be exactly
`accession_id,title,collection,updated_at`. This order is part of the public
feed contract. Every accession ID must be present and unique. Confirm that no
internal notes or patron data appears in any field.

Compare the data row count with the current public snapshot. The acceptable
change is up to 2% in either direction. If it exceeds 2%, pause the export until
the collection owner explains the difference and confirms that it is expected.
Record both row counts and the percentage in the review notes.

After review, copy the current file to the dated archive and verify that the
copy opens and has the same row count as the current public snapshot. Replace
`catalog-public.csv` with the reviewed candidate. Download the published file
and verify its columns and row count against the candidate.
